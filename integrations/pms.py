"""Синхронизация доступности: PMS API → Google Sheets → локальная таблица.

Приоритет:
  1. PMS (Bnovo / Travelline / Shelter), если заданы PMS_API_URL + ключ;
  2. Google Sheets, если задан GOOGLE_SHEET_ID;
  3. Локальная таблица availability (демо / ручное ведение администратором).
"""
import asyncio
import logging
from datetime import date, timedelta

from config import settings
import db

log = logging.getLogger("pms")


async def sync_once() -> int:
    """Один цикл синхронизации. Возвращает число обновлённых строк."""
    if settings.PMS_API_URL:
        try:
            return await _from_pms()
        except Exception as e:  # сбой PMS не должен ронять бота
            log.warning("PMS недоступен (%s), пробуем Sheets/локальную таблицу", e)
    if settings.GOOGLE_SHEET_ID:
        try:
            return await _from_sheets()
        except Exception as e:
            log.warning("Google Sheets недоступна (%s), используем локальную таблицу", e)
    return 0


async def _from_pms() -> int:
    """GET {PMS}/availability?from&to — формат под Bnovo/Travelline-подобных API."""
    import aiohttp
    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=settings.HORIZON_DAYS)).isoformat()
    url = f"{settings.PMS_API_URL}/availability"
    params = {"from": today, "to": horizon}
    headers = {"Authorization": f"Bearer {settings.PMS_API_KEY}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers=headers,
                         timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}")
            rows = await r.json()
    # Формат ответа: [{"unit_id": 1, "date": "2026-10-24", "free": true, "price": 3500}]
    updated = 0
    for row in rows:
        updated += db._exec(
            "INSERT OR REPLACE INTO availability (unit_id, day, is_free, price)"
            " VALUES (?,?,?,?)",
            (int(row["unit_id"]), row["date"], int(bool(row.get("free"))),
             float(row.get("price") or 0)))
    return updated


async def _from_sheets() -> int:
    """Таблица: колонка A = id домика, далее колонки-даты, значение = 0 или цена."""
    import gspread  # pip install gspread  (см. requirements.txt)
    gc = gspread.service_account(filename=settings.GOOGLE_CREDS_FILE)
    sh = gc.open_by_key(settings.GOOGLE_SHEET_ID).worksheet("availability")
    records = sh.get_all_records()  # первая строка — заголовки с датами
    updated = 0
    for row in records:
        unit_id = int(row.get("id") or row.get("ID") or 0)
        for day_iso, val in row.items():
            if not isinstance(day_iso, str) or len(day_iso) < 8:
                continue
            try:
                date.fromisoformat(day_iso)
            except ValueError:
                continue
            is_free = 0 if (val in (0, "0", "занято", "Занято", "")) else 1
            price = float(val) if is_free and str(val).replace(".", "").isdigit() else 0
            updated += db._exec(
                "INSERT OR REPLACE INTO availability (unit_id, day, is_free, price)"
                " VALUES (?,?,?,?)", (unit_id, day_iso, is_free, price))
    return updated


async def sync_loop(interval_sec: int = 1800) -> None:
    """Фоновый цикл: сразу и далее каждые 30 минут."""
    while True:
        try:
            n = await sync_once()
            if n:
                log.info("Доступность обновлена: %s строк", n)
        except Exception as e:
            log.warning("Синхронизация не удалась: %s", e)
        await asyncio.sleep(interval_sec)
