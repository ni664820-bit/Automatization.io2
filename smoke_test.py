"""Smoke-тест: проверяет схему БД, витрину, приём заявки, follow-up и метрики
без подключения к Telegram. Запуск: python smoke_test.py
"""
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("BITRIX_WEBHOOK_URL", None)
os.environ.pop("ADMIN_CHAT_ID", None)

import db  # noqa: E402
from services.booking_service import submit_booking  # noqa: E402
from services import metrics  # noqa: E402
from services.followups import run_due  # noqa: E402


async def main() -> None:
    db.init_db()
    print("1. init_db OK, units:", len(db._rows("SELECT * FROM units")))

    types = db.unit_types()
    assert types, "нет типов размещения"
    print("2. unit_types:", types)

    d_in, d_out = "2026-11-10", "2026-11-12"  # вторник-четверг: не «занятые» ночи
    units = db.free_units(d_in, d_out, None, 3)
    assert units, "витрина пуста на тестовые даты"
    print(f"3. free_units: {len(units)} шт., первый: {units[0]['name']}")

    booking = await submit_booking(None, {
        "date_in": d_in, "date_out": d_out, "adults": 2, "children": 1,
        "unit_id": units[0]["id"], "wishes": ["Баня", "Завтрак"],
        "name": "Тест Тестов", "phone": "+79000000000", "tg_id": 42,
        "channel": "telegram",
    })
    assert booking and booking["status"] == "new", "заявка не создана"
    print(f"4. submit_booking OK: №{booking['id']}, {booking['total']} ₽")

    fu = db._rows("SELECT * FROM followups WHERE booking_id = ?", (booking["id"],))
    assert len(fu) == 4, f"ожидалось 4 напоминания, есть {len(fu)}"
    print(f"5. followups запланировано: {len(fu)}")

    # эмуляция админа: подтверждение освобождает ночи
    db.set_booking_status(booking["id"], "confirmed")
    b = db.get_booking(booking["id"])
    assert b["status"] == "confirmed"
    print("6. set_booking_status OK")

    m = db.metrics(7)
    assert m["bookings"] >= 1 and m["total_in"] >= 1, f"метрики пустые: {m}"
    print("7. metrics:", {k: m[k] for k in ("bookings", "auto_share", "conversion")})

    report = metrics.report(7)
    assert "Метрики" in report
    csv_data = metrics.export_csv(30)
    assert csv_data.read(10)
    print("8. отчёт + CSV OK")

    sent = await run_due(None)  # напоминания на сегодняшнюю дату в демо-базе
    print(f"9. due follow-ups отправлено: {sent} (0 — норма, время не наступило)")

    # дедупликация гостя
    g1 = db.upsert_guest(42, "+79000000000", "Тест Тестов")
    g2 = db.upsert_guest(43, "+79000000000", "Другой")
    assert g1 == g2, "дедупликация по телефону не сработала"
    print("10. дедупликация гостя OK")

    print("\nSMOKE TEST PASSED ✅")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
