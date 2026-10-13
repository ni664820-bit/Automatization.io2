"""Обработка заявки: гость → бронь → CRM → уведомление администратору.

Единая точка входа для всех каналов (Telegram, сайт, WhatsApp — через webhook).
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import db
from bot.keyboards import admin_booking_menu
from config import settings
from integrations import bitrix24, notify


def _object_tz():
    """Часовой пояс объекта; если tzdata недоступна — UTC."""
    try:
        return ZoneInfo(settings.TZ)
    except Exception:
        return timezone.utc


def _schedule_reminders(booking_id: int, date_in: str) -> None:
    """Напоминания клиенту за 3 и 1 день до заезда в 10:00 по TZ объекта.

    Времена хранятся в UTC — сравнение с due-проверками корректно
    при любом поясе.
    """
    tz = _object_tz()
    d_in = date.fromisoformat(date_in)
    for kind, delta in (("reminder_3d", 3), ("reminder_1d", 1)):
        local_noon = datetime.combine(d_in - timedelta(days=delta),
                                      time(hour=10), tzinfo=tz)
        when_utc = local_noon.astimezone(timezone.utc)
        db.schedule_followup(booking_id, kind, when_utc.strftime("%Y-%m-%d %H:%M:%S"))
    # follow-up, если заявку так и не подтвердили
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for kind, hours in (("abandoned_24h", 24), ("abandoned_48h", 48)):
        db.schedule_followup(booking_id, kind,
                             (now + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S"))


async def submit_booking(bot, data: dict) -> dict | None:
    """data: {date_in, date_out, adults, children, unit_id/any, wishes[], name, phone, tg_id}"""
    # 1. Витрина могла устареть — проверяем, что домик действительно свободен
    units = db.free_units(data["date_in"], data["date_out"])
    guests_n = data["adults"] + data.get("children", 0)
    units = [u for u in units if u["capacity_adult"] + u["capacity_children"] >= guests_n]
    if data.get("unit_id") and data["unit_id"] != "any":
        units = [u for u in units if u["id"] == data["unit_id"]]
    if not units:
        return None  # обработчик предложит новые даты
    unit = units[0]

    # 2. Дедупликация гостя по телефону/TG → история повторного гостя
    guest_id = db.upsert_guest(data["tg_id"], data.get("phone"), data.get("name"))

    # 3. Локальная запись брони (статус new — до подтверждения админом)
    nights = (date.fromisoformat(data["date_out"]) - date.fromisoformat(data["date_in"])).days
    # wishes приходит либо индексами WISHES (из FSM), либо готовыми названиями
    wish_names = [db.WISHES[i] if isinstance(i, int) else str(i)
                  for i in (data.get("wishes") or [])]
    booking_id = db.insert_booking(
        guest_id=guest_id, unit_id=unit["id"],
        date_in=data["date_in"], date_out=data["date_out"],
        adults=data["adults"], children=data.get("children", 0),
        wishes=",".join(wish_names),
        source=data.get("channel", "telegram"),
        total=unit["price"] * nights)

    booking = db.get_booking(booking_id)

    # 4. Лид в Bitrix24 (ретраи внутри; при выключенной интеграции — тихо мимо)
    lead_id = await bitrix24.create_lead(booking)
    if lead_id:
        db._exec("UPDATE bookings SET bitrix_lead_id = ? WHERE id = ?", (lead_id, booking_id))

    # 5. Мгновенное уведомление администратору с кнопками подтверждения
    await notify.notify_admins(bot, notify.booking_card(booking),
                               reply_markup=admin_booking_menu(booking_id))

    # 6. Источник метрик + напоминания
    db.record_touchpoint(guest_id, "telegram", "in", "booking",
                         f"заявка №{booking_id}", "bot", booking_id)
    _schedule_reminders(booking_id, data["date_in"])
    return booking
