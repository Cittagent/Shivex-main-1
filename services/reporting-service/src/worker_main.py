import asyncio
import logging

from src.workers.report_worker import ReportWorker


logging.basicConfig(level=logging.INFO)


def main() -> None:
    asyncio.run(ReportWorker().start())


if __name__ == "__main__":
    main()
