"""E2E-тест: прогоняет полный диалог бота через фейковую Telegram-сессию
(без сети). Сценарии: /start,FAQ, бронирование до подтверждения админом,
эскалация и ответ через /reply. Запуск: python e2e_test.py
"""
import os
import tempfile
from datetime import datetime

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "e2e.db")
os.environ["BITRIX_WEBHOOK_URL"] = ""
os.environ["ADMIN_CHAT_ID"] = "999"
os.environ["ADMIN_USER_IDS"] = "777"

from aiogram import Bot  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import Chat, Message, Update  # noqa: E402

import db  # noqa: E402
from bot import build_dp  # noqa: E402

SENT: list[tuple[str, str]] = []  # (имя метода, текст)


class FakeSession(BaseSession):
    """Перехватывает все исходящие вызовы Telegram API, ничего не шлёт."""

    async def close(self):  # noqa: D102
        pass

    async def stream_content(self, *args, **kwargs):  # noqa: D102
        yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: D102
        name = type(method).__name__
        text = getattr(method, "text", None) or getattr(method, "caption", "")
        SENT.append((name, text or ""))
        if name in ("AnswerCallbackQuery",):
            return True
        if name in ("SendMessage", "EditMessageText", "EditMessageReplyMarkup",
                    "SendDocument"):
            chat_id = getattr(method, "chat_id", 42)
            return Message(message_id=len(SENT), date=datetime.now(),
                           chat=Chat(id=int(chat_id), type="private"))
        return True


def msg_update(update_id: int, text: str | None = None, contact=None,
               user_id: int = 42, chat_id: int = 42) -> Update:
    raw = {"update_id": update_id,
           "message": {"message_id": update_id, "date": 1700000000,
                       "chat": {"id": chat_id, "type": "private"},
                       "from": {"id": user_id, "is_bot": False,
                                "first_name": "Тест", "last_name": "Тестов"}}}
    if text is not None:
        raw["message"]["text"] = text
    if contact is not None:
        raw["message"]["contact"] = {"phone_number": contact,
                                     "user_id": user_id, "first_name": "Тест"}
    return Update.model_validate(raw, context={"bot": BOT})


def cb_update(update_id: int, data: str, text: str = "диалог",
              user_id: int = 42, chat_id: int = 42) -> Update:
    raw = {"update_id": update_id,
           "callback_query": {"id": str(update_id), "data": data,
                              "chat_instance": "ci",
                              "from": {"id": user_id, "is_bot": False,
                                       "first_name": "Тест"},
                              "message": {"message_id": update_id,
                                          "date": 1700000000, "text": text,
                                          "chat": {"id": chat_id,
                                                   "type": "private"}}}}
    return Update.model_validate(raw, context={"bot": BOT})


def last_text() -> str:
    """Текст последнего отправленного сообщения (игнорирует ответы кнопок)."""
    for name, text in reversed(SENT):
        if name == "SendMessage":
            return text
    return ""


async def main() -> None:
    global BOT
    db.init_db()
    BOT = Bot(token="42:TEST", session=FakeSession())
    dp = build_dp()

    async def send(uid, *a, **k):
        await dp.feed_update(BOT, msg_update(uid, *a, **k))

    async def click(uid, *a, **k):
        await dp.feed_update(BOT, cb_update(uid, *a, **k))

    # 1. старт
    await send(1, "/start")
    assert "Привет" in last_text(), last_text()
    print("1. /start OK")

    # 2. FAQ
    await send(2, "📋 Услуги и FAQ")
    assert "вопрос" in last_text().lower(), last_text()
    await click(3, "faq:bath")
    assert "баня" in last_text().lower(), last_text()
    print("2. FAQ OK")

    # 3. свободные даты
    await send(4, "📅 Свободные даты")
    assert "Загрузка" in last_text(), last_text()
    print("3. витрина 14 дней OK")

    # 4. полный квиз бронирования
    await send(5, "🏠 Забронировать")
    assert "Выберите даты" in last_text(), last_text()
    assert any("дата заезда" in t.lower() for n, t in SENT), "приветствие квиза не отправлено"

    await click(6, "cal:in:2026-11-10")
    await click(7, "cal:out:2026-11-12")
    await click(8, "cal:done")
    assert "Сколько вас будет" in last_text(), last_text()
    print("4. календарь OK")

    await click(9, "g:2:1")            # 2 взрослых + ребёнок
    assert "размещение" in last_text().lower(), last_text()

    await click(10, "bk:type:Комфорт")
    assert "Свободно" in last_text(), last_text()
    print("5. витрина доступности OK")

    unit = db.free_units("2026-11-10", "2026-11-12", "Комфорт", 3)
    assert unit, "нет свободных «Комфорт»"
    await click(11, f"bk:unit:{unit[0]['id']}")
    await click(12, "w:0")             # пожелание: баня
    await click(13, "w:next")
    assert "контакт" in last_text().lower(), last_text()
    print("6. пожелания OK")

    await send(14, contact="+79000000001")
    assert "Проверьте заявку" in last_text(), last_text()
    print("7. сводка OK:", last_text().splitlines()[0])

    await click(15, "bk:confirm")
    assert "Заявка №1" in last_text(), last_text()
    b = db.get_booking(1)
    assert b and b["status"] == "new" and b["phone"] == "+79000000001"
    # уведомление админу с кнопками ушло в чат 999
    admin_msgs = [t for n, t in SENT if n == "SendMessage" and "Новая заявка" in t]
    assert admin_msgs, "админ не получил заявку"
    print("8. заявка создана, уведомление админу ушло OK")

    # 9. админ подтверждает кнопкой из чата 999
    await click(16, f"adm:ok:1", user_id=777, chat_id=999)
    assert db.get_booking(1)["status"] == "confirmed", "не подтвердилось"
    assert any("подтверждена" in t for n, t in SENT if n == "SendMessage"), \
        "клиент не получил подтверждение"
    print("9. подтверждение админом OK")

    # 10. админ-метрики
    await send(17, "/metrics", user_id=777, chat_id=999)
    assert "Метрики" in last_text(), last_text()
    print("10. /metrics OK")

    # 11. эскалация: ключевое слово → админу, затем /reply клиенту
    await send(18, "Хочу поговорить с оператором")
    assert any("Подключаю администратора" in t for n, t in SENT), "клиент не получил приветствие эскалации"
    assert any("Клиент перешёл к оператору" in t for n, t in SENT), "админ не уведомлён"
    await send(19, "Это тестовое сообщение оператору")
    assert any("Принял, передал" in t for n, t in SENT), "клиенту нет подтверждения"
    assert any("Это тестовое сообщение оператору" in t for n, t in SENT), "сообщение не продублировано админу"
    await send(20, "/reply 42 Здравствуйте! Отвечаем в течение 15 минут.",
               user_id=777, chat_id=999)
    assert any("Здравствуйте!" in t for n, t in SENT), "ответ не доставлен клиенту"
    print("11. эскалация + /reply OK")

    # 12. завершение разговора + нераспознанный текст → подсказка
    await send(21, "⛔ Завершить разговор")
    assert "завершён" in last_text().lower(), last_text()
    await send(22, "аывапрол")
    assert "понял" in last_text().lower(), last_text()
    print("12. fallback OK")

    # 13. метрики отражают всё сказанное
    m = db.metrics(7)
    assert m["bookings"] == 1 and m["escalations"] >= 2 and m["faq_hits"] >= 1, m
    print("13. метрики:", m)

    print("\nE2E TEST PASSED ✅  Всего API-вызовов:", len(SENT))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
