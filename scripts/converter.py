import uuid
from pathlib import Path

from PIL import Image

from scripts.utils import get_unique_path


def convert_webp(image_path: Path) -> Path:
    """Convert WebP to verified PNG/APNG, preserving the source on failure."""
    if image_path.suffix.lower() != ".webp":
        return image_path

    target = get_unique_path(image_path.parent, f"{image_path.stem}.png")
    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp.png")

    try:
        with Image.open(image_path) as source:
            frame_count = getattr(source, "n_frames", 1)
            loop = source.info.get("loop", 0)
            frames: list[Image.Image] = []
            durations: list[int] = []
            for index in range(frame_count):
                source.seek(index)
                frames.append(source.convert("RGBA").copy())
                durations.append(int(source.info.get("duration", 0)))

        save_options: dict[str, object] = {"format": "PNG"}
        if frame_count > 1:
            save_options.update(
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=loop,
            )
        frames[0].save(temporary, **save_options)

        with Image.open(temporary) as converted:
            converted.load()
            if getattr(converted, "n_frames", 1) != frame_count:
                raise ValueError("WebP 转换后帧数不一致")

        temporary.replace(target)
        try:
            image_path.unlink()
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
