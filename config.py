"""Конфигурация бота: читает .env и отдаёт настройки в одном месте."""
import os
from dotenv import load_dotenv

load_dotenv()


def _int_list(raw: str) -> list[int]:
    """'1,2,3' -> [1, 2, 3]"""
    return [int(x) for x in raw.replace(";", ",").split(",") if x.strip().isdigit()]


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_CHAT_ID: int = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)
    ADMIN_USER_IDS: list[int] = _int_list(os.getenv("ADMIN_USER_IDS", ""))
    TZ: str = os.getenv("TZ", "Europe/Moscow")

    DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")

    BITRIX_WEBHOOK_URL: str = os.getenv("BITRIX_WEBHOOK_URL", "").rstrip("/") + "/" \
        if os.getenv("BITRIX_WEBHOOK_URL") else ""

    PMS_API_URL: str = os.getenv("PMS_API_URL", "")
    PMS_API_KEY: str = os.getenv("PMS_API_KEY", "")

    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "")
    GOOGLE_CREDS_FILE: str = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")

    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_LOGIN: str = os.getenv("SMTP_LOGIN", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

    OBJECT_NAME: str = os.getenv("OBJECT_NAME", "База отдыха «Пример»")

    # Порт HTTP health-check (для Docker/мониторинга); 0 — выключен
    HEALTH_PORT: int = int(os.getenv("HEALTH_PORT", "8080"))
    # Файл логов (ротация 5 МБ × 3); пусто — только в консоль
    LOG_FILE: str = os.getenv("LOG_FILE", "")

    # Сколько дней вперёд показываем витрину доступности
    HORIZON_DAYS: int = 60
    # SLA подтверждения заявки администратором, минут
    SLA_MINUTES: int = 15


settings = Settings()
