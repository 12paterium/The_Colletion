import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from scripts.utils import CATEGORIES, RequestPacer, clean_filename, image_data_url


@dataclass(frozen=True)
class Provider:
    api_key_env: str
    base_url: str
    default_model: str


@dataclass(frozen=True)
class ImageDecision:
    mark: str
    category: str


PROVIDERS = {
    "qwen": Provider(
        api_key_env="QWEN_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.8-max",
    ),
    "siliconflow": Provider(
        api_key_env="SILICONFLOW_API_KEY",
        base_url="https://api.siliconflow.cn/v1",
        default_model="Qwen/Qwen3-VL-32B-Instruct",
    ),
}

REQUEST_INTERVAL = 0.07
REQUEST_TIMEOUT = 60.0

PROMPT = """
观察图片，并以 JSON 对象返回中文文件名和分类，只允许两个字段：
{"mark":"警察 你继续说","category":"表情"}

文件名要求：
- 模仿中国互联网梗图或表情包命名，优先人物或来源加台词、短吐槽、动作或情绪。
- 使用口语和必要的网络用语，不要书面总结，不要解释。
- 目标长度 8 至 20 个字，只使用文字、数字和空格，不使用标点。

category 必须严格四选一，并按以下顺序判断：
1. 表情：主要适合在聊天中直接表达反应、情绪或动作，可脱离原始故事反复使用。
2. 史：聊天记录、帖子、推文、长文本或依赖故事上下文才能理解的离谱、接地气内容。
3. 梗图：内容短小集中，一个笑点即可理解，通常让人会心一笑。
4. 其他：壁纸、插画、素材、普通照片、信息图，或无法稳定归入前三类。

必须输出合法 JSON，不要 Markdown 代码块，不要增加 reason、confidence 等字段。
""".strip()


def parse_decision(content: str) -> ImageDecision:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型未返回合法 JSON：{exc}") from exc

    if not isinstance(payload, dict) or set(payload) != {"mark", "category"}:
        raise ValueError("模型 JSON 必须只包含 mark 和 category")

    mark = payload["mark"]
    category = payload["category"]
    if not isinstance(mark, str) or not isinstance(category, str):
        raise ValueError("模型 JSON 的 mark 和 category 必须是字符串")
    if category not in CATEGORIES:
        raise ValueError(f"未知分类：{category}")
    return ImageDecision(mark=clean_filename(mark), category=category)


def load_provider() -> tuple[Provider, str, str]:
    provider_name = os.getenv("AI_PROVIDER", "qwen").lower()
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(f"未知提供商 {provider_name!r}，可选值：{', '.join(PROVIDERS)}")

    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(f"请设置环境变量 {provider.api_key_env}")
    return provider, api_key, os.getenv("AI_MODEL") or provider.default_model


def create_client(provider: Provider, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=provider.base_url,
        timeout=REQUEST_TIMEOUT,
        max_retries=2,
    )


async def analyze_image(
    client: Any,
    model: str,
    image_path: Path,
    pacer: RequestPacer,
) -> tuple[ImageDecision, int]:
    data_url = await asyncio.to_thread(image_data_url, image_path)
    await pacer.wait()

    raw_response = await client.chat.completions.with_raw_response.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=120,
        temperature=0.35,
    )
    response = raw_response.parse()
    content = response.choices[0].message.content
    if not content:
        raise ValueError("模型未返回内容")
    return parse_decision(content), raw_response.status_code
