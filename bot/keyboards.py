"""Главные клавиатуры (ReplyKeyboard) и inline-клавиатуры."""
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

from db import faq_list, services_list

BTN_BOOK = "🏠 Забронировать"
BTN_DATES = "📅 Свободные даты"
BTN_FAQ = "📋 Услуги и FAQ"
BTN_SERVICES = "🍽 Доп. услуги"
BTN_MY = "👤 Мои брони"
BTN_OPERATOR = "💬 Оператор"
BTN_STOP = "⛔ Завершить разговор"
BTN_CONTACT = "📱 Отправить мой контакт"


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню — всегда доступно, включая кнопку живого оператора."""
    kb = [
        [KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_DATES)],
        [KeyboardButton(text=BTN_FAQ), KeyboardButton(text=BTN_SERVICES)],
        [KeyboardButton(text=BTN_MY), KeyboardButton(text=BTN_OPERATOR)],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def stop_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_STOP)]], resize_keyboard=True)


def contact_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CONTACT, request_contact=True)],
                  [KeyboardButton(text="✏️ Ввести номер вручную")]],
        resize_keyboard=True, input_field_placeholder="+7 900 000-00-00")


def faq_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"❓ {f['question']}", callback_data=f"faq:{f['slug']}")]
            for f in faq_list()]
    rows.append([InlineKeyboardButton(text="💬 Задать вопрос оператору",
                                      callback_data="op:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{s['name']} — {int(s['price'])} ₽",
                                  callback_data=f"svc:{s['id']}")]
            for s in services_list()]
    rows.append([InlineKeyboardButton(text="🏠 К бронированию", callback_data="bk:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summary_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="bk:confirm"),
        InlineKeyboardButton(text="✏️ Изменить", callback_data="bk:restart"),
    ]])


def unit_menu(units: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for u in units:
        label = f"{u['name']} — {int(u['price'])} ₽/ночь"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"bk:unit:{u['id']}")])
    rows.append([InlineKeyboardButton(text="🎲 Подобрать любой вариант", callback_data="bk:unit:any")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="bk:restart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def type_menu(types: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t, callback_data=f"bk:type:{t}")] for t in types]
    rows.append([InlineKeyboardButton(text="Любой вариант", callback_data="bk:type:Любой")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_booking_menu(booking_id: int) -> InlineKeyboardMarkup:
    """Кнопки в уведомлении администратору: подтвердить/отклонить заявку."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm:ok:{booking_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm:no:{booking_id}"),
    ], [InlineKeyboardButton(text="💬 Ответить (/reply)", callback_data="adm:help")]])
