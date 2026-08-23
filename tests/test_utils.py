import asyncio
import base64
import tempfile
import unittest
from pathlib import Path

from scripts.utils import (
    CATEGORIES,
    RequestPacer,
    clean_filename,
    discover_images,
    get_unique_path,
    image_data_url,
)


class UtilsTests(unittest.TestCase):
    def test_discover_images_only_returns_direct_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "b.png").write_bytes(b"b")
            (root / "a.JPG").write_bytes(b"a")
            (root / "video.mp4").write_bytes(b"v")
            (root / "梗图").mkdir()
            (root / "梗图" / "nested.png").write_bytes(b"n")

            self.assertEqual(
                [path.name for path in discover_images(root)],
                ["a.JPG", "b.png"],
            )

    def test_image_data_url_uses_extension_mime_and_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "example.webp"
            image.write_bytes(b"webp-content")

            encoded = base64.b64encode(b"webp-content").decode("ascii")
            self.assertEqual(
                image_data_url(image),
                f"data:image/webp;base64,{encoded}",
            )

    def test_clean_filename_removes_windows_illegal_characters(self) -> None:
        self.assertEqual(
            clean_filename('  警察:*  你继续说?.  '),
            "警察 你继续说",
        )

    def test_clean_filename_rejects_empty_result(self) -> None:
        with self.assertRaisesRegex(ValueError, "空文件名"):
            clean_filename('  <>:"/\\|?*  ')

    def test_clean_filename_avoids_windows_reserved_names(self) -> None:
        self.assertEqual(clean_filename("CON"), "_CON")

    def test_get_unique_path_adds_incrementing_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "重复.jpg").write_bytes(b"first")
            (root / "重复_1.jpg").write_bytes(b"second")

            self.assertEqual(
                get_unique_path(root, "重复.jpg"),
                root / "重复_2.jpg",
            )

    def test_categories_have_exact_output_folder_names(self) -> None:
        self.assertEqual(CATEGORIES, ("梗图", "表情", "史", "其他"))


class RequestPacerTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_separates_concurrent_request_starts(self) -> None:
        pacer = RequestPacer(0.02)

        async def wait_and_record() -> float:
            await pacer.wait()
            return asyncio.get_running_loop().time()

        first, second = await asyncio.gather(wait_and_record(), wait_and_record())

        # Windows' monotonic clock can report a boundary a few ulps below
        # the requested delay. A 10 ms lower bound still catches a missing
        # pacing wait without asserting floating-point equality.
        self.assertGreaterEqual(second - first, 0.01)


if __name__ == "__main__":
    unittest.main()
