import asyncio
import logging

from scripts.sorter import sort_directory


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    try:
        summary = asyncio.run(sort_directory())
    except (FileNotFoundError, ValueError) as exc:
        logging.error("无法启动：%s", exc)
        raise SystemExit(1) from exc

    logging.info("处理完成：成功 %d 张，失败 %d 张", summary.succeeded, summary.failed)


if __name__ == "__main__":
    main()
