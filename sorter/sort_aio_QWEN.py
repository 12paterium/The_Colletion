import asyncio
import argparse
import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path

from openai import AsyncOpenAI
from tqdm import tqdm


# ===== 提供商配置 =====
@dataclass(frozen=True)
class Provider:
    api_key_env: str
    base_url: str
    default_model: str


# 添加提供商时，在这里填写：API Key 环境变量名、OpenAI 兼容接口地址、默认模型。
PROVIDERS = {
    "qwen": Provider(
        api_key_env="QWEN_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.7-plus",
    ),
    "siliconflow": Provider(
        api_key_env="SILICONFLOW_API_KEY",
        base_url="https://api.siliconflow.cn/v1",
        default_model="Qwen/Qwen3-VL-32B-Instruct",
    ),
}

PROVIDER_NAME = os.getenv("AI_PROVIDER", "qwen").lower()
MODEL_OVERRIDE = os.getenv("AI_MODEL")

IMAGE_DIR = Path("./待归档")
HISTORY_FILE = Path(__file__).with_name("sort_history.json")
REQUEST_INTERVAL = 0.07  # 相邻请求的最短启动间隔，防止限流
MAX_CONCURRENT = 6
REQUEST_TIMEOUT = 60.0
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

PROMPT = """
请给这个表情包生成一个中文文件名，模仿中国互联网常见表情包命名风格：

要求：
1. 可以包含人物或来源（如：警察、葛优、贴吧表情等）
2. 优先使用短句、吐槽、命令句或情绪表达
3. 允许网络用语、抽象表达(仅在有必要时候)
4. 不要标点符号（除了空格）
5. 控制在 8-20 个字
6. 输出仅一行文件名，不要解释
7. 尽量避免过于通顺或书面语，可以略微不自然或口语化

风格分布（尽量随机）：
- 人物+台词（如：警察 你继续说）
- 吐槽句（如：被生活压扁）
- 攻击/命令句（如：说 你是猪）
- 贴吧表情风格（如：贴吧表情 滑稽流汗）

示例：
警察 你继续说
葛优 你要是唠这个我可不困了
贴吧表情 滑稽流汗
让我先尝尝你的味道
被生活压扁
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# OpenAI SDK 底层会通过 httpx 输出每一次 HTTP 请求；正常运行时无需展示。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


# ===== 工具函数 =====
def encode_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


def image_data_url(image_path: Path) -> str:
    mime_type = IMAGE_MIME_TYPES.get(image_path.suffix.lower())
    if mime_type is None:
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    return f"data:{mime_type};base64,{encode_image(image_path)}"


def calculate_sha256(image_path: Path) -> str:
    digest = hashlib.sha256()
    with image_path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_history() -> dict[str, str]:
    if not HISTORY_FILE.exists():
        return {}

    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in data.items()
        ):
            raise ValueError("记录文件格式不正确")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"无法读取历史记录 {HISTORY_FILE.name}，为避免重复重命名，已停止：{exc}"
        ) from exc


def save_history(history: dict[str, str]) -> None:
    temp_file = HISTORY_FILE.with_suffix(".tmp")
    content = json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True)
    temp_file.write_text(content + "\n", encoding="utf-8")
    temp_file.replace(HISTORY_FILE)


def select_pending_images(
    images: list[Path],
    hashes: list[str],
    history: dict[str, str],
) -> tuple[list[tuple[Path, str]], int, bool]:
    pending_images: list[tuple[Path, str]] = []
    skipped = 0
    history_changed = False

    for image, image_hash in zip(images, hashes):
        recorded_name = history.get(image_hash)
        if recorded_name is None:
            pending_images.append((image, image_hash))
            continue

        # 同一内容已经处理过。名称不同表示用户后来手工修正了文件名；
        # 接受该修正并同步记录，避免下次运行时被模型覆盖。
        if recorded_name != image.name:
            history[image_hash] = image.name
            history_changed = True
        skipped += 1

    return pending_images, skipped, history_changed


def clean_filename(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r"\s+", " ", text)
    text = text[:40].rstrip(". ")

    if not text:
        raise ValueError("模型返回了空文件名")

    return text


def get_unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1

    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1

    return candidate


class RequestPacer:
    """控制请求启动频率，同时不阻塞其他异步任务。"""

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


async def generate_name(
    client: AsyncOpenAI,
    model: str,
    image_path: Path,
    pacer: RequestPacer,
) -> tuple[str, int]:
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
        max_tokens=80,
        temperature=0.6,
    )
    response = raw_response.parse()

    content = response.choices[0].message.content
    if not content:
        raise ValueError("模型未返回文件名")

    return clean_filename(content), raw_response.status_code


async def process_image(
    client: AsyncOpenAI,
    model: str,
    semaphore: asyncio.Semaphore,
    rename_lock: asyncio.Lock,
    history_lock: asyncio.Lock,
    history: dict[str, str],
    pacer: RequestPacer,
    image_path: Path,
    image_hash: str,
) -> bool:
    async with semaphore:
        try:
            description, status_code = await generate_name(
                client,
                model,
                image_path,
                pacer,
            )

            # 锁住“检查重名 + 重命名”，防止并发任务生成相同名称。
            async with rename_lock:
                new_path = get_unique_path(
                    image_path.parent,
                    f"{description}{image_path.suffix}",
                )
                await asyncio.to_thread(image_path.rename, new_path)
                # 重命名本身不会更新文件修改时间，显式 touch 为当前时间。
                await asyncio.to_thread(new_path.touch)

            # 每张成功后立即保存，意外中断时也能保留已经完成的记录。
            async with history_lock:
                history[image_hash] = new_path.name
                await asyncio.to_thread(save_history, history)

            tqdm.write(f"{status_code} | {new_path.name}")
            return True
        except Exception as exc:
            status_code = getattr(exc, "status_code", "ERROR")
            tqdm.write(f"{status_code} | {image_path.name} | 失败：{exc}")
            return False


# ===== 主流程 =====
def load_provider() -> tuple[Provider, str, str]:
    provider = PROVIDERS.get(PROVIDER_NAME)
    if provider is None:
        choices = ", ".join(PROVIDERS)
        raise ValueError(f"未知提供商 {PROVIDER_NAME!r}，可选值：{choices}")

    api_key = os.getenv(provider.api_key_env)
    if not api_key:
        raise ValueError(f"请设置环境变量 {provider.api_key_env}")

    return provider, api_key, MODEL_OVERRIDE or provider.default_model


async def main(check_only: bool = False) -> None:
    provider, api_key, model = load_provider()

    if not IMAGE_DIR.is_dir():
        raise FileNotFoundError(f"图片目录不存在：{IMAGE_DIR.resolve()}")

    images = sorted(
        path
        for path in IMAGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )

    logger.info(
        "启动：提供商=%s，模型=%s，并发=%d",
        PROVIDER_NAME,
        model,
        MAX_CONCURRENT,
    )
    logger.info("找到 %d 张待处理图片", len(images))

    if not images:
        return

    pacer = RequestPacer(REQUEST_INTERVAL)

    if check_only:
        pending_images: list[tuple[Path, str]] = []
        skipped = 0
    else:
        history = load_history()
        hashes = await asyncio.gather(
            *(asyncio.to_thread(calculate_sha256, image) for image in images)
        )
        pending_images, skipped, history_changed = select_pending_images(
            images,
            hashes,
            history,
        )
        if history_changed:
            await asyncio.to_thread(save_history, history)
            logger.info("已同步手工修改的文件名到历史记录")
        logger.info("跳过 %d 张，待处理 %d 张", skipped, len(pending_images))

        if not pending_images:
            return

    async with AsyncOpenAI(
        api_key=api_key,
        base_url=provider.base_url,
        timeout=REQUEST_TIMEOUT,
        max_retries=2,
    ) as client:
        if check_only:
            generated_name, status_code = await generate_name(
                client,
                model,
                images[0],
                pacer,
            )
            logger.info("%s | %s%s（测试模式，未重命名）", status_code, generated_name, images[0].suffix)
            return

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        rename_lock = asyncio.Lock()
        history_lock = asyncio.Lock()
        tasks = [
            asyncio.create_task(
                process_image(
                    client,
                    model,
                    semaphore,
                    rename_lock,
                    history_lock,
                    history,
                    pacer,
                    image_path,
                    image_hash,
                )
            )
            for image_path, image_hash in pending_images
        ]

        succeeded = 0
        with tqdm(total=len(tasks), desc="处理图片", unit="张") as progress:
            for task in asyncio.as_completed(tasks):
                succeeded += await task
                progress.update(1)

    failed = len(pending_images) - succeeded
    logger.info("处理完成：成功 %d 张，失败 %d 张，跳过 %d 张", succeeded, failed, skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="异步生成图片文件名并批量重命名")
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅测试第一张图片的模型调用，不重命名任何文件",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(check_only=args.check))
    except (FileNotFoundError, ValueError) as exc:
        logger.error("无法启动：%s", exc)
        raise SystemExit(1) from exc
