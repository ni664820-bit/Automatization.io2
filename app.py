"""Точка входа: python app.py

Запускает бота (polling), фоновые задачи: синхронизация доступности
(PMS/Sheets), напоминания/follow-up и HTTP /health для мониторинга.
"""
import asyncio
import logging
import os
import signal
from logging.handlers import RotatingFileHandler

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from bot import build_dp
from bot.fsm_storage import SQLiteStorage
from config import settings
from db import close_db, init_db
from health import run_health_server
from integrations.pms import sync_loop
from services.followups import followup_loop


def setup_logging() -> None:
    """Консоль + опциональный файл с ротацией (для VPS/сервиса)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.LOG_FILE:
        os.makedirs(os.path.dirname(settings.LOG_FILE) or ".", exist_ok=True)
        handlers.append(RotatingFileHandler(
            settings.LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=handlers)


async def main() -> None:
    if not settings.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан — заполните файл .env (см. .env.example)")

    setup_logging()
    log = logging.getLogger("app")

    init_db()  # схема + демо-данные при первом запуске
    log.info("База готова: %s", settings.DB_PATH)

    bot = Bot(settings.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=None))
    dp = build_dp(storage=SQLiteStorage())  # диалоги переживают рестарт

    bg: list[asyncio.Task] = [
        asyncio.create_task(followup_loop(bot), name="followups"),
        asyncio.create_task(sync_loop(), name="pms-sync")]
    if settings.HEALTH_PORT:
        bg.append(asyncio.create_task(run_health_server(settings.HEALTH_PORT),
                                      name="health"))

    # Graceful shutdown: SIGTERM (docker stop) / CTRL+C — корректный выход
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, current.cancel)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: сработает KeyboardInterrupt от asyncio.run

    log.info("Бот запускается... CTRL+C / docker stop — остановка")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except asyncio.CancelledError:
        log.info("Получен сигнал остановки, завершаюсь…")
    finally:
        for t in bg:
            t.cancel()
        await asyncio.gather(*bg, return_exceptions=True)
        close_db()
        log.info("Остановлено.")


if __name__ == "__main__":
    asyncio.run(main())
