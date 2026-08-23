import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.converter import convert_webp


class ConverterTests(unittest.TestCase):
    def test_static_webp_becomes_png_and_removes_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "static.webp"
            Image.new("RGBA", (4, 4), "red").save(source, "WEBP")

            result = convert_webp(source)

            self.assertEqual(result.suffix, ".png")
            self.assertTrue(result.exists())
            self.assertFalse(source.exists())

    def test_animated_webp_preserves_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "animated.webp"
            frames = [Image.new("RGBA", (4, 4), color) for color in ("red", "blue")]
            frames[0].save(
                source,
                "WEBP",
                save_all=True,
                append_images=frames[1:],
                duration=[80, 120],
                loop=2,
            )

            result = convert_webp(source)

            with Image.open(result) as converted:
                self.assertEqual(converted.n_frames, 2)
                self.assertEqual(converted.info.get("loop"), 2)

    def test_corrupt_webp_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "broken.webp"
            source.write_bytes(b"not-webp")

            with self.assertRaises(Exception):
                convert_webp(source)

            self.assertTrue(source.exists())
            self.assertEqual(list(Path(temp).glob("*.png")), [])


if __name__ == "__main__":
    unittest.main()
