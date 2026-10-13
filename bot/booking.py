"""Квиз бронирования: даты → гости → тип → витрина → пожелания →
контакт → сводка → подтверждение (заявка в CRM + админу)."""
import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from bot.calendar_kb import month_view
from bot.keyboards import (BTN_CONTACT, contact_menu, main_menu,
                           summary_menu, type_menu, unit_menu)
from bot.states import Booking
from config import settings
from db import WISHES
from services.booking_service import submit_booking

router = Router(name="booking")

PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{9,}\d")


def _guests_kb():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 взрослый", callback_data="g:1:0"),
         InlineKeyboardButton(text="2 взрослых", callback_data="g:2:0")],
        [InlineKeyboardButton(text="2+1 ребёнок", callback_data="g:2:1"),
         InlineKeyboardButton(text="2+2 ребёнка", callback_data="g:2:2")],
        [InlineKeyboardButton(text="3 взрослых", callback_data="g:3:0"),
         InlineKeyboardButton(text="4 взрослых", callback_data="g:4:0")],
    ])


def _wishes_kb(selected: list[int]):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for i, w in enumerate(WISHES):
        mark = "✅ " if i in selected else "▫️ "
        rows.append([InlineKeyboardButton(text=mark + w, callback_data=f"w:{i}")])
    rows.append([
        InlineKeyboardButton(text="Далее ➡️", callback_data="w:next"),
        InlineKeyboardButton(text="Без пожеланий", callback_data="w:none"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_booking(target, state: FSMContext) -> None:
    """Точка входа в квиз (из меню или кнопки «К бронированию»)."""
    await state.clear()
    await state.set_state(Booking.dates)
    await state.update_data(date_in=None, date_out=None, wishes=[], channel="telegram")
    today = date.today()
    await target.answer(
        "🏠 <b>Онлайн-бронирование</b>\nСначала — дата заезда 🟨 "
        "(фиолетовым — выезд). Занятые даты помечены ✖",
        parse_mode="HTML")
    await target.answer("Выберите даты:",
                        reply_markup=month_view(today.year, today.month, None, None))


# --- даты (inline-календарь) -----------------------------------------------
@router.callback_query(Booking.dates, F.data.startswith("cal:"))
async def on_calendar(cb: CallbackQuery, state: FSMContext):
    _, action, *rest = cb.data.split(":")  # "cal:in:2026-11-10" → ("in", ["2026-11-10"])
    data = await state.get_data()
    d_in = date.fromisoformat(data["date_in"]) if data.get("date_in") else None
    d_out = date.fromisoformat(data["date_out"]) if data.get("date_out") else None

    if action == "nav":
        y, m = map(int, rest[0].split("-"))
        await cb.message.edit_reply_markup(reply_markup=month_view(y, m, d_in, d_out))
        return await cb.answer()
    if action == "in":
        d_in, d_out = date.fromisoformat(rest[0]), None
    elif action == "out":
        day = date.fromisoformat(rest[0])
        if d_in and day > d_in:
            d_out = day
        else:
            return await cb.answer("Выезд должен быть позже заезда ⚠️", show_alert=True)
    elif action == "done":
        if not (d_in and d_out):
            return await cb.answer("Выберите обе даты", show_alert=True)
        await state.update_data(date_in=d_in.isoformat(), date_out=d_out.isoformat())
        await state.set_state(Booking.guests)
        await cb.message.edit_reply_markup()  # прячем календарь
        await cb.message.answer(
            f"📅 Заезд {d_in.strftime('%d.%m')}, выезд {d_out.strftime('%d.%m')}.\n"
            "Сколько вас будет?", reply_markup=_guests_kb())
        return await cb.answer("Даты выбраны ✅")
    else:
        return await cb.answer()

    await state.update_data(date_in=d_in.isoformat() if d_in else None,
                            date_out=d_out.isoformat() if d_out else None)
    await cb.message.edit_reply_markup(
        reply_markup=month_view(d_in.year, d_in.month, d_in, d_out))
    await cb.answer("Запомнено ✅" if d_in and d_out else "Теперь выберите выезд")


# --- гости -----------------------------------------------------------------
@router.callback_query(Booking.guests, F.data.startswith("g:"))
async def on_guests(cb: CallbackQuery, state: FSMContext):
    _, adults, children = cb.data.split(":")
    await state.update_data(adults=int(adults), children=int(children))
    await state.set_state(Booking.unit_type)
    await cb.message.edit_reply_markup()
    await cb.message.answer(
        "Какое размещение предпочитаете? Показу только свободные на ваши даты.",
        reply_markup=type_menu(db.unit_types()))
    await cb.answer()


@router.message(Booking.guests, F.text)
async def on_guests_text(msg: Message, state: FSMContext):
    nums = [int(n) for n in re.findall(r"\d+", msg.text)]
    adults = nums[0] if nums else 2
    children = nums[1] if len(nums) > 1 else 0
    await state.update_data(adults=adults, children=children)
    await state.set_state(Booking.unit_type)
    await msg.answer("Какое размещение предпочитаете?",
                     reply_markup=type_menu(db.unit_types()))


# --- тип и витрина доступности ---------------------------------------------
@router.callback_query(Booking.unit_type, F.data.startswith("bk:type:"))
async def on_type(cb: CallbackQuery, state: FSMContext):
    unit_type = cb.data.split(":", 2)[2]
    data = await state.get_data()
    await state.update_data(unit_type=unit_type)
    units = db.free_units(data["date_in"], data["date_out"],
                          None if unit_type == "Любой" else unit_type,
                          data["adults"] + data.get("children", 0))
    if not units:
        # Fallback: не тупик, а другой тип + подписка на освобождение
        other = db.unit_types()
        await cb.answer("На эти даты такого типа свободно мало…", show_alert=True)
        await cb.message.answer(
            "Свободных вариантов такого типа на ваши даты нет. "
            "Выберите другой тип — или напишите оператору, подберём альтернативу.",
            reply_markup=type_menu(other))
        return
    await state.set_state(Booking.unit_pick)
    await cb.message.answer(
        f"🏡 Свободно {len(units)} вариантов на {data['date_in']} — {data['date_out']}:",
        reply_markup=unit_menu(units))
    await cb.answer()


@router.callback_query(Booking.unit_pick, F.data.startswith("bk:unit:"))
async def on_unit(cb: CallbackQuery, state: FSMContext):
    unit_id = cb.data.split(":")[2]
    await state.update_data(unit_id=unit_id)
    await state.set_state(Booking.wishes)
    data = await state.get_data()
    await cb.message.answer(
        "Есть пожелания? (баня, завтрак, собака, трансфер…)",
        reply_markup=_wishes_kb(data.get("wishes") or []))
    await cb.answer()


@router.callback_query(Booking.wishes, F.data.startswith("w:"))
async def on_wishes(cb: CallbackQuery, state: FSMContext):
    action = cb.data.split(":")[1]
    data = await state.get_data()
    wishes: list[int] = list(data.get("wishes") or [])
    if action.isdigit():
        i = int(action)
        if i in wishes:
            wishes.remove(i)
        else:
            wishes.append(i)
        await state.update_data(wishes=wishes)
        await cb.message.edit_reply_markup(reply_markup=_wishes_kb(wishes))
        return await cb.answer()
    if action == "none":
        wishes = []
    await state.update_data(wishes=wishes)
    await state.set_state(Booking.contact)
    await cb.message.edit_reply_markup()
    await cb.message.answer(
        "📱 Отправьте контакт одной кнопкой — или введите номер вручную:",
        reply_markup=contact_menu())
    await cb.answer()


# --- контакт ---------------------------------------------------------------
@router.message(Booking.contact, F.contact)
async def on_contact(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.contact.phone_number,
                            name=msg.contact.full_name or msg.from_user.full_name)
    await _to_summary(msg, state)


@router.message(Booking.contact, F.text)
async def on_contact_text(msg: Message, state: FSMContext):
    if msg.text == BTN_CONTACT:
        return
    m = PHONE_RE.search(msg.text)
    if not m:
        return await msg.answer("Не нашёл номер 📞 Введите его в формате: +7 900 000-00-00")
    phone = re.sub(r"\D", "", m.group(0))
    if not phone.startswith("8") and not phone.startswith("7"):
        phone = "7" + phone
    elif phone.startswith("8"):
        phone = "7" + phone[1:]
    name = (msg.text[:m.start()] + msg.text[m.end():]).strip(" ,.-") \
        or msg.from_user.full_name
    await state.update_data(phone="+" + phone, name=name)
    await _to_summary(msg, state)


async def _to_summary(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    units = db.free_units(data["date_in"], data["date_out"],
                          None if data.get("unit_type") == "Любой" else data.get("unit_type"),
                          data["adults"] + data.get("children", 0))
    if data.get("unit_id") and data["unit_id"] != "any":
        chosen = [u for u in units if str(u["id"]) == str(data["unit_id"])]
        units = chosen or units
    if not units:
        await state.clear()
        return await msg.answer("Извините, свободных домиков не осталось 😔 "
                                "Начнём заново?", reply_markup=main_menu())
    unit = units[0]
    nights = (date.fromisoformat(data["date_out"]) - date.fromisoformat(data["date_in"])).days
    wishes = ", ".join(WISHES[i] for i in sorted(data.get("wishes") or [])) or "—"
    await state.update_data(unit_id=unit["id"], unit_name=unit["name"],
                            total=unit["price"] * nights, wishes_list=wishes)
    await state.set_state(Booking.summary)
    await msg.answer(
        f"📋 <b>Проверьте заявку</b>\n"
        f"📅 {data['date_in']} → {data['date_out']} ({nights} ноч.)\n"
        f"👥 {data['adults']} взр. + {data['children']} дет.\n"
        f"🏡 {unit['name']} — {int(unit['price'])} ₽/ночь, итого {int(unit['price'] * nights)} ₽\n"
        f"💬 {wishes}\n"
        f"👤 {data.get('name')} · {data.get('phone')}\n\n"
        "Всё верно?",
        parse_mode="HTML", reply_markup=summary_menu())


# --- подтверждение ---------------------------------------------------------
@router.callback_query(Booking.summary, F.data == "bk:confirm")
async def on_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    data["tg_id"] = cb.from_user.id
    booking = await submit_booking(cb.bot, data)
    if not booking:
        await cb.answer("Домик только что заняли — выберите другие даты",
                        show_alert=True)
        await state.set_state(Booking.dates)
        await state.update_data(date_in=None, date_out=None)
        await cb.message.answer("Выберите другие даты:",
                                reply_markup=month_view(date.today().year,
                                                        date.today().month, None, None))
        return
    await state.clear()
    await cb.message.edit_reply_markup()
    await cb.message.answer(
        f"✅ <b>Заявка №{booking['id']} принята!</b>\n"
        f"{booking['unit_name']}, {booking['date_in']} → {booking['date_out']}.\n"
        f"Администратор подтвердит наличие в течение {settings.SLA_MINUTES} минут — "
        "сообщим здесь же. Хорошего отдыха! 🌲",
        parse_mode="HTML", reply_markup=main_menu())
    await cb.answer("Заявка отправлена ✅")


@router.callback_query(Booking.summary, F.data == "bk:restart")
async def on_restart(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_booking(cb.message, state)


@router.callback_query(F.data == "bk:start")
async def on_start_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await start_booking(cb.message, state)
