import asyncio
import base64
import mimetypes
import re
from pathlib import Path


IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
CATEGORIES = ("梗图", "表情", "史", "其他")
SORTING_DIR = Path(__file__).resolve().parents[1] / "sorting"

IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


def discover_images(directory: Path) -> list[Path]:
    """Return supported direct child images in deterministic order."""
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def image_data_url(image_path: Path) -> str:
    """Encode an image as a MIME-correct base64 data URL."""
    mime_type = IMAGE_MIME_TYPES.get(image_path.suffix.lower())
    if mime_type is None:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def clean_filename(text: str) -> str:
    """Normalize a model-generated Windows-safe filename stem."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text.strip())
    cleaned = re.sub(r'[\\/*?:"<>|]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned[:40].rstrip(". ")

    if not cleaned:
        raise ValueError("模型返回了空文件名")
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def get_unique_path(directory: Path, filename: str) -> Path:
    """Return a non-existing sibling path without overwriting files."""
    candidate = directory / filename
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1

    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


class RequestPacer:
    """Serialize request starts while allowing requests themselves to overlap."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            delay = self.interval - (loop.time() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = loop.time()
