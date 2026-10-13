"""Inline-календарь выбора дат заезда/выезда.

callback_data:
  cal:nav:<год>-<месяц>  — листание месяцев
  cal:in:<дата>          — дата заезда
  cal:out:<дата>         — дата выезда
"""
from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def month_view(year: int, month: int, date_in: date | None,
               date_out: date | None) -> InlineKeyboardMarkup:
    """Календарь одного месяца; занятые дни не нажимаются."""
    rows = [[InlineKeyboardButton(text=f"{MONTHS[month - 1]} {year}",
                                  callback_data="cal:none")]]
    first = date(year, month, 1)
    # листание
    prev_m = (date(year, month, 1) - timedelta(days=1))
    next_m = (date(year, month, 28) + timedelta(days=7)).replace(day=1)
    rows.append([
        InlineKeyboardButton(text="←", callback_data=f"cal:nav:{prev_m.year}-{prev_m.month}"),
        InlineKeyboardButton(text="→", callback_data=f"cal:nav:{next_m.year}-{next_m.month}"),
    ])
    rows.append([InlineKeyboardButton(text=wd, callback_data="cal:none") for wd in WD])

    # сетка дней
    row: list[InlineKeyboardButton] = []
    for _ in range(first.weekday()):       # пустые ячейки до начала месяца
        row.append(InlineKeyboardButton(text="—", callback_data="cal:none"))
    last_day = (next_m - timedelta(days=1)).day
    for day_num in range(1, last_day + 1):
        d = date(year, month, day_num)
        if d < date.today():
            row.append(InlineKeyboardButton(text="·", callback_data="cal:none"))
        elif db.day_load(d.isoformat()) == 0:          # полностью занято
            row.append(InlineKeyboardButton(text=f"{day_num}✖", callback_data="cal:none"))
        else:
            mark = ""
            if d == date_in:
                mark = "🟨"
            elif d == date_out:
                mark = "🟪"
            cb = "cal:in" if (date_in is None or d <= date_in or date_out is not None) else "cal:out"
            if date_in is not None and date_out is None and d > date_in:
                cb = "cal:out"
            elif d == date_in and date_out is None:
                cb = "cal:in"
            row.append(InlineKeyboardButton(text=f"{mark}{day_num}",
                                            callback_data=f"{cb}:{d.isoformat()}"))
        if len(row) == 7:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if date_in and date_out:
        rows.append([InlineKeyboardButton(text="✅ Даты выбраны — далее",
                                          callback_data="cal:done")])
    else:
        hint = "Сначала — дата заезда 🟨" if date_in is None else "Теперь — дата выезда 🟪"
        rows.append([InlineKeyboardButton(text=hint, callback_data="cal:none")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
