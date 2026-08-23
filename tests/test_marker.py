import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.marker import ImageDecision, analyze_image, parse_decision


class FakeRawResponse:
    status_code = 200

    def __init__(self, content: str) -> None:
        self.content = content

    def parse(self) -> SimpleNamespace:
        message = SimpleNamespace(content=self.content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeCreate:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def __call__(self, **kwargs: object) -> FakeRawResponse:
        self.calls += 1
        if kwargs.get("response_format") != {"type": "json_object"}:
            raise AssertionError("request must enable JSON Object mode")
        return FakeRawResponse(self.content)


class FakePacer:
    async def wait(self) -> None:
        return None


class MarkerTests(unittest.TestCase):
    def test_parse_decision_returns_clean_valid_fields(self) -> None:
        self.assertEqual(
            parse_decision('{"mark":" 警察:* 你继续说? ","category":"表情"}'),
            ImageDecision(mark="警察 你继续说", category="表情"),
        )

    def test_parse_decision_rejects_unknown_category(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知分类"):
            parse_decision('{"mark":"名字","category":"未知"}')

    def test_parse_decision_rejects_missing_or_non_string_fields(self) -> None:
        invalid_payloads = (
            '{"category":"表情"}',
            '{"mark":3,"category":"表情"}',
            '["名字", "表情"]',
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_decision(payload)


class AnalyzeImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_image_makes_one_json_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "input.jpg"
            image.write_bytes(b"image")
            create = FakeCreate('{"mark":"熊猫头 你退下吧","category":"梗图"}')
            client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(
                        with_raw_response=SimpleNamespace(create=create)
                    )
                )
            )

            decision, status = await analyze_image(
                client,
                "vision-model",
                image,
                FakePacer(),
            )

            self.assertEqual(decision.category, "梗图")
            self.assertEqual(status, 200)
            self.assertEqual(create.calls, 1)


if __name__ == "__main__":
    unittest.main()
