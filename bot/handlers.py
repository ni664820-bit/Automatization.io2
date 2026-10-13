"""Хендлеры бота, разделены на 3 роутера по приоритету (порядок подключения):

1. menu_router  — кнопки главного меню (работают в любом состоянии);
2. cmd_router   — команды (/start, /metrics, /reply, ...) и админ-функции;
3. router       — FAQ, доп. услуги, эскалация, fallback.

Сценарий бронирования (bot/booking.py) подключается между 2 и 3.
"""
from datetime import date, datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from bot.booking import start_booking
from bot.keyboards import (BTN_BOOK, BTN_DATES, BTN_FAQ, BTN_MY, BTN_OPERATOR,
                           BTN_SERVICES, BTN_STOP, faq_menu, main_menu,
                           services_menu)
from bot.states import Escalation
from config import settings
from integrations import notify
from services import metrics

menu_router = Router(name="menu")
cmd_router = Router(name="commands")
router = Router(name="handlers")

MENU_TEXTS = {BTN_BOOK, BTN_DATES, BTN_FAQ, BTN_SERVICES, BTN_MY, BTN_OPERATOR, BTN_STOP}
ESCALATION_KEYWORDS = ("оператор", "человек", "администратор", "позвонить",
                       "менеджер", "живой")

# Активные диалоги с оператором: tg_id -> время последнего входящего
ACTIVE_ESCALATIONS: dict[int, datetime] = {}


def _is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_USER_IDS


def _guest_id(tg_id: int) -> int | None:
    g = db._one("SELECT id FROM guests WHERE tg_id = ?", (tg_id,))
    return g["id"] if g else None


# ===========================================================================
# 1. ГЛАВНОЕ МЕНЮ — работает в любом состоянии
# ===========================================================================
@menu_router.message(F.text.in_(MENU_TEXTS))
async def on_menu(msg: Message, state: FSMContext):
    text = msg.text

    if text == BTN_STOP:
        ACTIVE_ESCALATIONS.pop(msg.from_user.id, None)
        await state.clear()
        return await msg.answer("Разговор завершён. Если что — я на месте 👇",
                                reply_markup=main_menu())

    if text == BTN_BOOK:
        return await start_booking(msg, state)

    await state.clear()  # любой другой пункт меню — выход из текущего сценария

    if text == BTN_DATES:
        db.record_touchpoint(_guest_id(msg.from_user.id), "telegram", "in",
                             "availability", "свободные даты")
        lines = []
        for i in range(14):
            d = date.today() + timedelta(days=i)
            free = db.day_load(d.isoformat())
            mark = f"🟢 {free} дом." if free else "🔴 занято"
            lines.append(f"{d.strftime('%d.%m %a')}: {mark}")
        return await msg.answer("📅 <b>Загрузка на 14 дней</b>\n" + "\n".join(lines),
                                parse_mode="HTML", reply_markup=main_menu())

    if text == BTN_FAQ:
        return await msg.answer("Выберите вопрос — отвечу сразу:",
                                reply_markup=faq_menu())

    if text == BTN_SERVICES:
        return await msg.answer("🍽 <b>Доп. услуги и цены</b>", parse_mode="HTML",
                                reply_markup=services_menu())

    if text == BTN_MY:
        rows = db.guest_bookings(msg.from_user.id)
        if not rows:
            return await msg.answer("У вас пока нет броней. Начнём? 🏠",
                                    reply_markup=main_menu())
        status_ru = {"new": "⏳ ждёт подтверждения", "confirmed": "✅ подтверждена",
                     "prepaid": "💳 предоплата получена", "declined": "❌ отклонена",
                     "cancelled": "🚫 отменена"}
        body = "\n".join(
            f"№{r['id']} · {r['date_in']}→{r['date_out']} · "
            f"{r.get('unit_name') or '—'} · {status_ru.get(r['status'], r['status'])}"
            for r in rows)
        return await msg.answer("👤 <b>Ваши брони:</b>\n" + body, parse_mode="HTML")

    if text == BTN_OPERATOR:
        await _escalate(msg, state)


# ===========================================================================
# 2. КОМАНДЫ: клиентские и админские
# ===========================================================================
@cmd_router.message(F.text.startswith("/"))
async def on_command(msg: Message, state: FSMContext):
    cmd = msg.text.split()[0].lower()
    is_admin = _is_admin(msg.from_user.id) or msg.chat.id == settings.ADMIN_CHAT_ID

    if cmd == "/id":
        return await msg.answer(f"Ваш user id: <code>{msg.from_user.id}</code>\n"
                                f"chat id: <code>{msg.chat.id}</code>",
                                parse_mode="HTML")

    if cmd == "/start":
        if is_admin:
            return await msg.answer(
                "🔧 <b>Админ-панель</b>\n"
                "/metrics — метрики за 7 дней\n"
                "/bookings — очередь заявок\n"
                "/confirm N / decline N — статус заявки\n"
                "/reply ID текст — ответ клиенту\n"
                "/export — CSV истории обращений\n"
                "/id — ваши id", parse_mode="HTML")
        await state.clear()
        return await msg.answer(
            f"Привет! Я бот {settings.OBJECT_NAME} 🏠\n"
            "Помогу подобрать домик, узнать свободные даты и цены — "
            "займёт пару минут.",
            reply_markup=main_menu())

    if not is_admin:
        return await msg.answer("Неизвестная команда. Воспользуйтесь меню 👇",
                                reply_markup=main_menu())

    if cmd == "/metrics":
        return await msg.answer(metrics.report(7), parse_mode="HTML")

    if cmd == "/bookings":
        rows = db.recent_bookings()
        if not rows:
            return await msg.answer("Заявок пока нет.")
        body = "\n".join(
            f"№{r['id']} · {r['status']} · {r['date_in']}→{r['date_out']} · "
            f"{r.get('full_name')} · {r.get('phone')} · {r.get('unit_name') or '—'}"
            for r in rows)
        return await msg.answer("📋 <b>Последние заявки:</b>\n" + body,
                                parse_mode="HTML")

    if cmd in ("/confirm", "/decline") and len(msg.text.split()) >= 2:
        booking_id = int(msg.text.split()[1])
        status = "confirmed" if cmd == "/confirm" else "declined"
        booking = db.set_booking_status(booking_id, status)
        if not booking:
            return await msg.answer("Заявка не найдена.")
        if status == "confirmed":
            db.mark_booked(booking["unit_id"], booking["date_in"], booking["date_out"])
        await notify.notify_client(
            msg.bot, booking.get("tg_id") or 0,
            f"Статус заявки №{booking_id}: "
            f"{'✅ подтверждена' if status == 'confirmed' else '❌ отклонена'}")
        return await msg.answer(f"Заявка №{booking_id} → {status}")

    if cmd == "/reply":
        parts = msg.text.split(maxsplit=2)
        if len(parts) < 3 or not parts[1].isdigit():
            return await msg.answer("Формат: /reply 123456 Текст ответа")
        await notify.notify_client(msg.bot, int(parts[1]), parts[2])
        return await msg.answer("Отправлено клиенту ✅")

    if cmd == "/export":
        return await msg.answer_document(metrics.export_csv(30),
                                         caption="История обращений за 30 дней")

    return await msg.answer("Команда не распознана. /start — список команд.")


# ===========================================================================
# 3. FAQ, УСЛУГИ, ЭСКАЛАЦИЯ, FALLBACK
# ===========================================================================
@router.callback_query(F.data.startswith("faq:"))
async def on_faq(cb: CallbackQuery):
    slug = cb.data.split(":", 1)[1]
    art = db.faq_get(slug)
    await cb.answer()
    if not art:
        return
    db.record_touchpoint(_guest_id(cb.from_user.id), "telegram", "in", "faq", slug)
    await cb.message.answer(f"❓ <b>{art['question']}</b>\n\n{art['answer']}",
                            parse_mode="HTML", reply_markup=faq_menu())


@router.callback_query(F.data.startswith("svc:"))
async def on_service(cb: CallbackQuery):
    sid = int(cb.data.split(":")[1])
    svc = db._one("SELECT * FROM services WHERE id = ?", (sid,))
    await cb.answer()
    if not svc:
        return
    await cb.message.answer(
        f"🍽 <b>{svc['name']}</b>\nКатегория: {svc['category']}\n"
        f"Цена: {int(svc['price'])} ₽\n\n"
        "Заказать можно на этапе бронирования (пожелания) или у администратора.",
        parse_mode="HTML", reply_markup=services_menu())


async def _escalate(msg: Message, state: FSMContext) -> None:
    """Переводит диалог на живого администратора."""
    ACTIVE_ESCALATIONS[msg.from_user.id] = datetime.utcnow()
    await state.set_state(Escalation.chat)
    db.record_touchpoint(_guest_id(msg.from_user.id), "telegram", "in",
                         "escalation", "переход к оператору")
    await msg.answer(
        "💬 Подключаю администратора! Ответит здесь в течение "
        f"{settings.SLA_MINUTES} минут (ежедневно 9:00–21:00).",
        reply_markup=main_menu())
    await notify.notify_admins(
        msg.bot,
        f"💬 <b>Клиент перешёл к оператору</b>\n"
        f"tg: {msg.from_user.id} · @{msg.from_user.username or '—'} · "
        f"{msg.from_user.full_name}\n"
        f"Ответьте: /reply {msg.from_user.id} текст")


@router.message(Escalation.chat, F.text,
                ~F.text.in_(MENU_TEXTS), ~F.text.startswith("/"))
async def on_escalation_msg(msg: Message):
    """Сообщение клиента в живом диалоге → дублируется администратору."""
    ACTIVE_ESCALATIONS[msg.from_user.id] = datetime.utcnow()
    db.record_touchpoint(_guest_id(msg.from_user.id), "telegram", "in",
                         "escalation", msg.text)
    await notify.notify_admins(
        msg.bot,
        f"📨 <b>Клиент {msg.from_user.id}</b> (@{msg.from_user.username or '—'}):\n"
        f"{msg.text}\nОтвет: /reply {msg.from_user.id} текст")
    await msg.answer("Принял, передал администратору ⏳", reply_markup=main_menu())


# --- кнопки подтверждения заявки в чате администратора ---------------------
async def _admin_guard(cb: CallbackQuery) -> bool:
    if _is_admin(cb.from_user.id) or cb.message.chat.id == settings.ADMIN_CHAT_ID:
        return True
    await cb.answer("Нет прав подтверждать заявки", show_alert=True)
    return False


@router.callback_query(F.data.startswith("adm:"))
async def on_admin_action(cb: CallbackQuery):
    if not await _admin_guard(cb):
        return
    action, booking_id = cb.data.split(":")[1], int(cb.data.split(":")[2])
    if action == "help":
        return await cb.answer("Ответ клиенту: /reply <id> <текст>", show_alert=True)

    status = "confirmed" if action == "ok" else "declined"
    booking = db.set_booking_status(booking_id, status)
    if not booking:
        return await cb.answer("Заявка не найдена", show_alert=True)
    who = cb.from_user.full_name
    if action == "ok":
        db.mark_booked(booking["unit_id"], booking["date_in"], booking["date_out"])
        await notify.notify_client(
            cb.bot, booking.get("tg_id") or 0,
            f"🎉 <b>Бронь №{booking['id']} подтверждена!</b>\n"
            f"{booking.get('unit_name')}, {booking['date_in']} → {booking['date_out']}.\n"
            "Детали оплаты и геометку пришлём в ближайшее время.")
        await cb.answer("Подтверждено ✅")
        await cb.message.edit_text(f"✅ Подтверждено — {who}")
    else:
        await notify.notify_client(
            cb.bot, booking.get("tg_id") or 0,
            f"К сожалению, по заявке №{booking['id']} нет свободных вариантов 😔 "
            "Напишите нам — подберём альтернативные даты или домик.")
        await cb.answer("Отклонено ❌")
        await cb.message.edit_text(f"❌ Отклонено — {who}")


# --- fallback: подсказка вне сценария ---------------------------------------
@router.message(F.text)
async def on_fallback(msg: Message, state: FSMContext):
    low = (msg.text or "").lower()
    if any(k in low for k in ESCALATION_KEYWORDS):
        return await _escalate(msg, state)
    db.record_touchpoint(_guest_id(msg.from_user.id), "telegram", "in",
                         "fallback", msg.text)
    await msg.answer("Не совсем понял 🤔 Воспользуйтесь меню — "
                     "или спросите оператора:", reply_markup=main_menu())
