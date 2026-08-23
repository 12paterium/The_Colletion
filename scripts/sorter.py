import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from scripts.converter import convert_webp
from scripts.marker import ImageDecision, analyze_image, create_client, load_provider
from scripts.utils import CATEGORIES, RequestPacer, SORTING_DIR, discover_images, get_unique_path


logger = logging.getLogger(__name__)
MAX_CONCURRENT = 6
ImageAnalyzer = Callable[[Path], Awaitable[tuple[ImageDecision, int]]]


@dataclass(frozen=True)
class SortItemResult:
    source_path: Path
    final_path: Path | None
    decision: ImageDecision | None
    status_code: int | str
    error: str | None


@dataclass(frozen=True)
class SortSummary:
    results: tuple[SortItemResult, ...]

    @property
    def succeeded(self) -> int:
        return sum(result.error is None for result in self.results)

    @property
    def failed(self) -> int:
        return len(self.results) - self.succeeded


async def _sort_prepared(
    prepared: list[tuple[Path, Path]],
    analyzer: ImageAnalyzer,
) -> list[SortItemResult]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    move_lock = asyncio.Lock()

    async def process(source_path: Path, image_path: Path) -> SortItemResult:
        try:
            async with semaphore:
                decision, status_code = await analyzer(image_path)

            async with move_lock:
                destination = get_unique_path(
                    image_path.parent / decision.category,
                    f"{decision.mark}{image_path.suffix.lower()}",
                )
                await asyncio.to_thread(image_path.rename, destination)

            logger.info("%s | %s", status_code, destination.name)
            return SortItemResult(
                source_path=source_path,
                final_path=destination,
                decision=decision,
                status_code=status_code,
                error=None,
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", "ERROR")
            logger.error("%s | %s | 失败：%s", status_code, image_path.name, exc)
            return SortItemResult(
                source_path=source_path,
                final_path=None,
                decision=None,
                status_code=status_code,
                error=str(exc),
            )

    return list(
        await asyncio.gather(
            *(process(source_path, image_path) for source_path, image_path in prepared)
        )
    )


async def sort_directory(
    directory: Path = SORTING_DIR,
    analyzer: ImageAnalyzer | None = None,
) -> SortSummary:
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"图片目录不存在：{directory.resolve()}")

    for category in CATEGORIES:
        (directory / category).mkdir(exist_ok=True)

    conversion_failures: list[SortItemResult] = []
    prepared: list[tuple[Path, Path]] = []
    for source_path in discover_images(directory):
        try:
            image_path = await asyncio.to_thread(convert_webp, source_path)
            prepared.append((source_path, image_path))
        except Exception as exc:
            logger.error("ERROR | %s | 转换失败：%s", source_path.name, exc)
            conversion_failures.append(
                SortItemResult(source_path, None, None, "ERROR", str(exc))
            )

    if not prepared:
        return SortSummary(tuple(conversion_failures))

    if analyzer is not None:
        sorted_results = await _sort_prepared(prepared, analyzer)
    else:
        provider, api_key, model = load_provider()
        pacer = RequestPacer(0.07)
        async with create_client(provider, api_key) as client:

            async def production_analyzer(
                image_path: Path,
            ) -> tuple[ImageDecision, int]:
                return await analyze_image(client, model, image_path, pacer)

            sorted_results = await _sort_prepared(prepared, production_analyzer)

    return SortSummary(tuple(conversion_failures + sorted_results))
