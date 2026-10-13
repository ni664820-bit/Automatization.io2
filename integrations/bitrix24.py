"""Интеграция с Bitrix24 REST: создание лида по заявке, с повторами."""
import asyncio

import aiohttp

from config import settings
from db import record_touchpoint


async def create_lead(booking: dict) -> int | None:
    """Создаёт лид в Bitrix24. None — если интеграция выключена или упала
    (заявка при этом не теряется: она уже локально в БД и у админа в Telegram)."""
    if not settings.BITRIX_WEBHOOK_URL:
        return None
    url = f"{settings.BITRIX_WEBHOOK_URL}crm.lead.add.json"
    body = {
        "fields": {
            "TITLE": f"Запрос на бронь №{booking['id']} "
                     f"({booking['date_in']}–{booking['date_out']})",
            "NAME": booking.get("full_name") or "",
            "PHONE": [{"VALUE": booking.get("phone") or "", "VALUE_TYPE": "WORK"}],
            "SOURCE_ID": "WEB",
            "COMMENTS": (
                f"Канал: {booking.get('source')}\n"
                f"Гости: {booking['adults']} взр. + {booking['children']} дет.\n"
                f"Размещение: {booking.get('unit_name') or '—'}\n"
                f"Пожелания: {booking.get('wishes') or '—'}\n"
                f"Сумма: {booking.get('total') or 0} ₽\n"
                f"external_id: booking:{booking['id']}"),
        }
    }
    for attempt in range(3):  # 3 попытки с экспоненциальной паузой
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=body,
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                    js = await r.json()
                    if "result" in js:
                        record_touchpoint(booking.get("guest_id"), "bitrix24", "out",
                                          "crm", f"lead {js['result']}")
                        return int(js["result"])
                    raise RuntimeError(js.get("error_description", "unknown"))
        except Exception:
            if attempt == 2:
                return None
            await asyncio.sleep(2 ** attempt)
    return None
