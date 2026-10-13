"""Уведомления: Telegram-чат администратора, ответ клиенту, email-дубль."""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from config import settings

log = logging.getLogger("notify")


def booking_card(b: dict, for_admin: bool = True) -> str:
    """Текст карточки заявки (HTML)."""
    title = "Новая заявка" if for_admin else "Ваша заявка принята"
    return (
        f"🏠 <b>{title} №{b['id']}</b>\n"
        f"📅 {b['date_in']} → {b['date_out']}\n"
        f"👥 {b['adults']} взр. + {b['children']} дет.\n"
        f"👤 {b.get('full_name') or '—'} · {b.get('phone') or '—'}\n"
        f"🏡 {b.get('unit_name') or 'подбор варианта'}\n"
        f"💬 {(b.get('wishes') or '—').replace(',', ', ')}\n"
        f"💰 {int(b.get('total') or 0)} ₽\n"
        f"📡 Канал: {b.get('source') or 'telegram'}"
        + (f"\n⏱ Ответьте в течение {settings.SLA_MINUTES} мин"
           if for_admin else ""))


async def notify_admins(bot: Bot, text: str, reply_markup=None) -> None:
    """Уведомление в чат администратора + email-дубль, если настроен SMTP."""
    if not settings.ADMIN_CHAT_ID:
        log.warning("ADMIN_CHAT_ID не задан — уведомление не отправлено")
        return
    try:
        await bot.send_message(settings.ADMIN_CHAT_ID, text,
                               parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        log.error("Telegram-уведомление не ушло: %s", e)
    await _send_email("Новая заявка на бронирование", text)


async def notify_client(bot: Bot, tg_id: int, text: str) -> None:
    """Ответ клиенту тем же Telegram; ошибки доставки не роняют сценарий."""
    if not tg_id:
        return
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML")
    except TelegramForbiddenError:
        log.warning("Клиент %s заблокировал бота", tg_id)
    except Exception as e:
        log.error("Не доставлено клиенту %s: %s", tg_id, e)


async def _send_email(subject: str, html: str) -> None:
    if not settings.SMTP_HOST:
        return

    def _sync():
        msg = MIMEText(html, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_LOGIN
        msg["To"] = settings.SMTP_LOGIN
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as srv:
            srv.starttls()
            srv.login(settings.SMTP_LOGIN, settings.SMTP_PASSWORD)
            srv.send_message(msg)

    try:
        await asyncio.to_thread(_sync)
    except Exception as e:
        log.error("Email не ушёл: %s", e)
