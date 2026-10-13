"""Метрики пилота: текстовый отчёт и выгрузка touchpoints в CSV."""
import csv
import io
from datetime import datetime, timedelta

import db


def report(days: int = 7) -> str:
    m = db.metrics(days)
    return (
        f"📊 <b>Метрики за {days} дн.</b>\n"
        f"Входящих обращений: {m['total_in']}\n"
        f"Обработано ботом: {m['auto']} ({m['auto_share']}%) — цель 85%\n"
        f"FAQ-ответов ботом: {m['faq_hits']}\n"
        f"Эскалаций к оператору: {m['escalations']}\n"
        f"Заявок создано: {m['bookings']} · подтверждено: {m['confirmed']} "
        f"(конверсия {m['conversion']}%, цель +28% к базе)\n"
        f"Ждут подтверждения: {m['pending_confirm']} ⚠️\n"
        f"Follow-up отправлено: {m['followups_sent']} · в очереди: {m['followups_planned']}\n"
        f"\nКоманды: /bookings — очередь, /export — CSV истории")


def export_csv(days: int = 30) -> io.BytesIO:
    """CSV touchpoints за период — для BI/таблиц."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db._rows("SELECT * FROM touchpoints WHERE created_at >= ? ORDER BY id", (since,))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["id", "guest_id", "booking_id", "channel",
                                             "direction", "intent", "text",
                                             "answered_by", "created_at"])
    writer.writeheader()
    writer.writerows(rows)
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))  # BOM — для Excel
    data.name = f"touchpoints_{days}d.csv"
    return data
