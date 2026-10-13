"""Плановые напоминания и follow-up: цикл раз в минуту.

Виды follow-up:
  reminder_3d / reminder_1d — клиенту о скором заезде (только подтверждённые);
  abandoned_24h / abandoned_48h — клиенту, чью заявку администратор пока
      не подтвердил (вежливое напоминание + подтверждение, что места держим).
"""
import asyncio
import logging
from datetime import datetime

import db
from integrations import notify

log = logging.getLogger("followups")

TEXTS = {
    "reminder_3d": "Напоминание: через 3 дня ваш заезд! 🏠\n"
                   "Если планы изменились — сообщите, подкорректируем.\n"
                   "Что привезти/заказать заранее? Ответьте на это сообщение.",
    "reminder_1d": "Завтра ваш заезд! 🎉\n"
                   "Заезд с 14:00, координаты и геометку пришлём сюда.\n"
                   "Нужен трансфер или ранний заезд? Напишите нам.",
    "abandoned_24h": "Здравствуйте! Ваша заявка на бронирование всё ещё "
                     "актуальна — администратор подтвердит её в ближайшее время. "
                     "Если даты больше не нужны, напишите «отменить».",
    "abandoned_48h": "Вы ещё рассматриваете наши даты? 🏡 Свободные домики "
                     "разбирают быстро — подтвердим бронь за 15 минут, "
                     "если вы всё ещё планируете поездку.",
}


async def run_due(bot) -> int:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    sent = 0
    for fu in db.due_followups(now):
        booking = db.get_booking(fu["booking_id"])
        if not booking:
            db.followup_done(fu["id"])
            continue
        if fu["kind"].startswith("reminder") and booking["status"] not in ("confirmed", "prepaid"):
            # напоминания шлём только подтверждённым броням
            db.followup_done(fu["id"])
            continue
        if fu["kind"].startswith("abandoned") and booking["status"] != "new":
            # «заявка всё ещё актуальна» — только пока её не подтвердили
            db.followup_done(fu["id"])
            continue
        await notify.notify_client(bot, booking.get("tg_id") or 0,
                                   TEXTS.get(fu["kind"], ""))
        db.followup_done(fu["id"])
        db.record_touchpoint(booking.get("guest_id"), "telegram", "out",
                             "followup", fu["kind"], "bot", fu["booking_id"])
        sent += 1
    return sent


async def followup_loop(bot, interval_sec: int = 60) -> None:
    """Фоновая задача: опрос due-задач каждую минуту."""
    while True:
        try:
            n = await run_due(bot)
            if n:
                log.info("Отправлено follow-up: %s", n)
        except Exception as e:
            log.error("Ошибка follow-up: %s", e)
        await asyncio.sleep(interval_sec)
