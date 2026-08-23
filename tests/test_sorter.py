import tempfile
import unittest
from pathlib import Path

from scripts.marker import ImageDecision
from scripts.sorter import sort_directory


class SorterTests(unittest.IsolatedAsyncioTestCase):
    async def test_moves_image_to_decided_category_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "old.jpg"
            source.write_bytes(b"image")

            async def analyze(path: Path) -> tuple[ImageDecision, int]:
                return ImageDecision("熊猫头 你退下吧", "梗图"), 200

            summary = await sort_directory(root, analyzer=analyze)

            expected = root / "梗图" / "熊猫头 你退下吧.jpg"
            self.assertEqual(summary.succeeded, 1)
            self.assertEqual(summary.failed, 0)
            self.assertTrue(expected.exists())
            self.assertFalse(source.exists())

    async def test_failed_analysis_leaves_image_in_input_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "old.jpg"
            source.write_bytes(b"image")

            async def analyze(path: Path) -> tuple[ImageDecision, int]:
                raise RuntimeError("request failed")

            summary = await sort_directory(root, analyzer=analyze)

            self.assertEqual(summary.failed, 1)
            self.assertTrue(source.exists())

    async def test_existing_target_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "old.jpg"
            source.write_bytes(b"new")
            (root / "表情").mkdir()
            existing = root / "表情" / "猫猫 疑惑.jpg"
            existing.write_bytes(b"existing")

            async def analyze(path: Path) -> tuple[ImageDecision, int]:
                return ImageDecision("猫猫 疑惑", "表情"), 200

            await sort_directory(root, analyzer=analyze)

            self.assertEqual(existing.read_bytes(), b"existing")
            self.assertEqual((root / "表情" / "猫猫 疑惑_1.jpg").read_bytes(), b"new")

    async def test_nested_images_are_not_processed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "史").mkdir()
            nested = root / "史" / "done.jpg"
            nested.write_bytes(b"done")
            calls = 0

            async def analyze(path: Path) -> tuple[ImageDecision, int]:
                nonlocal calls
                calls += 1
                return ImageDecision("不应调用", "其他"), 200

            summary = await sort_directory(root, analyzer=analyze)

            self.assertEqual(calls, 0)
            self.assertEqual(len(summary.results), 0)
            self.assertTrue(nested.exists())


if __name__ == "__main__":
    unittest.main()
