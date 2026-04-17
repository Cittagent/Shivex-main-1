import asyncio

from app.workers.notification_worker import NotificationWorker


def main() -> None:
    asyncio.run(NotificationWorker().start())


if __name__ == "__main__":
    main()
