"""Хранилище данных: SQLite-схема (гости, брони, номера, услуги,
история обращений, FAQ, напоминания) + запросы.

Схема один-в-один повторяет проектную PostgreSQL-структуру — при
масштабировании достаточно перенести запросы на psycopg.
"""
import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

from config import settings

# папка под БД создаётся автоматически (важно при первом запуске из чистого клонирования)
os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
_conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS guests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE,
    phone TEXT UNIQUE,
    full_name TEXT,
    lang TEXT DEFAULT 'ru',
    is_recurrent INTEGER DEFAULT 0,
    consent_personal INTEGER DEFAULT 0,
    bitrix_contact_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    unit_type TEXT NOT NULL,
    capacity_adult INTEGER DEFAULT 2,
    capacity_children INTEGER DEFAULT 0,
    amenities TEXT DEFAULT '[]',
    pet_friendly INTEGER DEFAULT 0,
    base_price REAL DEFAULT 0,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guest_id INTEGER REFERENCES guests(id),
    unit_id INTEGER REFERENCES units(id),
    date_in TEXT NOT NULL,
    date_out TEXT NOT NULL,
    adults INTEGER NOT NULL,
    children INTEGER DEFAULT 0,
    status TEXT DEFAULT 'new',  -- new/confirmed/prepaid/cancelled/declined
    source TEXT,                -- telegram/website/whatsapp/...
    wishes TEXT,
    total REAL,
    handled_by_bot INTEGER DEFAULT 1,
    bitrix_lead_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS availability (
    unit_id INTEGER REFERENCES units(id),
    day TEXT,
    is_free INTEGER,
    price REAL,
    PRIMARY KEY (unit_id, day)
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    category TEXT,
    price REAL,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS booking_services (
    booking_id INTEGER REFERENCES bookings(id),
    service_id INTEGER REFERENCES services(id),
    qty INTEGER DEFAULT 1,
    PRIMARY KEY (booking_id, service_id)
);

CREATE TABLE IF NOT EXISTS touchpoints (  -- история обращений по каналам
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guest_id INTEGER,
    booking_id INTEGER,
    channel TEXT,
    direction TEXT,       -- in/out
    intent TEXT,          -- faq/booking/escalation/upsell
    text TEXT,
    answered_by TEXT,     -- bot/admin
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS faq_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    question TEXT,
    answer TEXT,
    lang TEXT DEFAULT 'ru',
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER REFERENCES bookings(id),
    kind TEXT,            -- reminder_3d/reminder_1d/abandoned_24h/abandoned_48h
    scheduled_at TEXT,
    sent_at TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS fsm (          -- персистентное состояние диалогов (FSM)
    k TEXT PRIMARY KEY,                   -- bot:chat:user:thread:destiny
    state TEXT,
    data TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tp_guest ON touchpoints (guest_id, created_at);
CREATE INDEX IF NOT EXISTS idx_bk_dates ON bookings (date_in, status);
CREATE INDEX IF NOT EXISTS idx_fu_sched ON followups (status, scheduled_at);
"""

# --- демо-данные: номерной фонд, услуги, FAQ -------------------------------
DEMO_UNITS = [
    ("Домик №1 «Лесной»",      "Стандарт", 2, 0, '["парковка"]',        0, 3500),
    ("Домик №2 «Лесной»",      "Стандарт", 2, 1, '["парковка"]',        0, 3500),
    ("Домик №3 «Комфорт»",     "Комфорт",  3, 1, '["баня","парковка"]', 1, 5200),
    ("Домик №4 «Комфорт»",     "Комфорт",  3, 2, '["баня","парковка"]', 1, 5200),
    ("Коттедж «Озеро»",        "Семейный", 4, 3, '["бассейн","баня"]',  1, 7900),
    ("Коттедж «Сосновый»",     "Семейный", 4, 2, '["бассейн"]',         1, 7400),
    ("VIP-домик «Панорама»",   "VIP",      2, 0, '["баня","бассейн"]',  0, 9800),
    ("Баня с бассейном (дом)","Услуга-дом", 0, 0, '["бассейн"]',        0, 0),
]

DEMO_SERVICES = [
    ("Завтрак (шведский стол)", "питание",   450),
    ("Ужин (3 подачи)",         "питание",   850),
    ("Экскурсия по окрестностям", "экскурсии", 1200),
    ("Спа-программа (1,5 ч)",   "спа",       3500),
    ("Прокат лыж/сноуборда",    "инвентарь", 700),
    ("Трансфер от вокзала",     "трансфер",  1500),
]

DEMO_FAQ = [
    ("bath", "Есть ли баня?",
     "Да! Русская баня на дровах, 3 часа — 3 000 ₽. В домиках «Комфорт», "
     "«Семейный» и «VIP» баня включена в стоимость. Записаться можно "
     "на этапе бронирования или на ресепшене."),
    ("pool", "Есть ли бассейн?",
     "Открытый подогреваемый бассейн работает с мая по сентябрь, "
     "10:00–20:00, вход включён в проживание. Зимой — крытый хаммам "
     "по записи (1 500 ₽/ч)."),
    ("breakfast", "Какой завтрак?",
     "Завтрак 8:00–10:30, шведский стол: каши, яичница, выпечка, "
     "свежие фрукты, кофе/чай. Детям — отдельное детское меню. "
     "Можно заказать ужин (3 подачи) — 850 ₽/чел."),
    ("parking", "Есть ли парковка?",
     "Бесплатная охраняемая парковка прямо у домиков, "
     "2 машины на каждый домик. Зарядка для электрокаров — 200 ₽/заряд."),
    ("pets", "Можно ли с собакой?",
     "Да, в домиках «Комфорт» и «Семейный» (кроме VIP). "
     "Мелкие и средние собаки — бесплатно, крупные — по согласованию. "
     "Просим отметить питомца при бронировании."),
    ("transfer", "Как организован трансфер?",
     "Трансфер от вокзала/аэропорта — 1 500 ₽, машина на 4 места, "
     "встреча с табличкой. Закажите на этапе бронирования или "
     "позвоните за 2 часа."),
    ("checkin", "Время заезда и выезда?",
     "Заезд с 14:00, выезд до 12:00. Ранний заезд и поздний выезд — "
     "по возможности, отметьте пожелание при бронировании — "
     "администратор подтвердит."),
    ("kids", "Детские услуги?",
     "Детская площадка, настольные игры, детское меню, скидка детям "
     "до 5 лет — проживание бесплатно (без доп. места), 5–12 лет — скидка 30%. "
     "По запросу — детская кроватка (500 ₽)."),
    ("payment", "Оплата и предоплита?",
     "Бронь без предоплита — просто подтверждение. Гарантией служит "
     "предоплита 30% за 3 дня до заезда. Оплата: перевод, карта, наличные "
     "на месте. Отмена бесплатна за 7 дней до заезда."),
    ("road", "Как добраться и где контакты?",
     "120 км от города, по указателям до озера, затем 3 км по лесной "
     "дороге (асфальт, зимой чистим). Точную геометку пришлём после "
     "подтверждения брони. Телефон ресепшена — в разделе «Оператор»."),
]

# Пожелания на этапе бронирования (мультивыбор)
WISHES = ["Баня", "Бассейн", "Завтрак", "Ужин", "С собакой",
          "Трансфер", "Ранний заезд", "Парковка"]


def init_db() -> None:
    """Создаёт схему и наполняет демо-данными при первом запуске."""
    with _lock, _conn:
        _conn.executescript(SCHEMA)
        if _conn.execute("SELECT COUNT(*) c FROM units").fetchone()["c"] == 0:
            _conn.executemany(
                "INSERT INTO units (name, unit_type, capacity_adult, capacity_children,"
                " amenities, pet_friendly, base_price) VALUES (?,?,?,?,?,?,?)",
                DEMO_UNITS)
            _conn.executemany(
                "INSERT INTO services (name, category, price) VALUES (?,?,?)",
                DEMO_SERVICES)
            _conn.executemany(
                "INSERT INTO faq_articles (slug, question, answer) VALUES (?,?,?)",
                DEMO_FAQ)
            _seed_availability()


def _seed_availability() -> None:
    """Демо-загрузка: 60 дней, часть домиков «занята» по выходным."""
    today = date.today()
    rows = []
    for unit in _conn.execute("SELECT id, base_price FROM units").fetchall():
        for i in range(settings.HORIZON_DAYS + 14):
            day = today + timedelta(days=i)
            # детерминированная «занятость» по выходным, чтобы витрина выглядела живой
            busy = (day.weekday() in (4, 5)) and (unit["id"] % 3 == i % 3)
            rows.append((unit["id"], day.isoformat(), 0 if busy else 1,
                         unit["base_price"] * (1.15 if day.weekday() in (4, 5) else 1)))
    _conn.executemany(
        "INSERT OR REPLACE INTO availability (unit_id, day, is_free, price) "
        "VALUES (?,?,?,?)", rows)


# --- утилиты ---------------------------------------------------------------
def _rows(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def _one(sql: str, params: tuple = ()) -> dict | None:
    with _lock:
        r = _conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def _exec(sql: str, params: tuple = ()) -> int:
    """INSERT/UPDATE c возвратом rowid."""
    with _lock, _conn:
        cur = _conn.execute(sql, params)
        return cur.lastrowid or cur.rowcount


# --- гости -----------------------------------------------------------------
def upsert_guest(tg_id: int, phone: str | None, name: str | None) -> int:
    g = _one("SELECT id FROM guests WHERE tg_id = ?", (tg_id,))
    if not g and phone:
        g = _one("SELECT id FROM guests WHERE phone = ?", (phone,))
    if g:
        _exec("UPDATE guests SET tg_id = COALESCE(tg_id, ?), full_name = COALESCE(?, full_name),"
              " is_recurrent = 1 WHERE id = ?",
              (tg_id, name, g["id"]))
        return g["id"]
    return _exec(
        "INSERT INTO guests (tg_id, phone, full_name, consent_personal) VALUES (?,?,?,1)",
        (tg_id, phone, name))


# --- витрина доступности ---------------------------------------------------
def free_units(date_in: str, date_out: str,
               unit_type: str | None = None,
               guests: int | None = None) -> list[dict]:
    """Домики, свободные все ночи [date_in, date_out), с ценой за ночь."""
    nights = [(date.fromisoformat(date_in) + timedelta(days=i)).isoformat()
              for i in range((date.fromisoformat(date_out) - date.fromisoformat(date_in)).days)]
    if not nights:
        return []
    placeholders = ",".join("?" * len(nights))
    sql = f"""
        SELECT u.id, u.name, u.unit_type, u.capacity_adult, u.capacity_children,
               u.amenities, u.pet_friendly, a.price
        FROM units u
        JOIN availability a ON a.unit_id = u.id AND a.day IN ({placeholders})
        WHERE u.active = 1
          AND u.id NOT IN (SELECT unit_id FROM availability
                           WHERE day IN ({placeholders}) AND is_free = 0)
        GROUP BY u.id
        HAVING COUNT(DISTINCT a.day) = ?
    """
    params = tuple(nights) + tuple(nights) + (len(nights),)
    result = []
    for r in _rows(sql, params):
        r["price"] = round(sum(x["price"] for x in _rows(
            f"SELECT price FROM availability WHERE unit_id = ? AND day IN ({placeholders})",
            (r["id"],) + tuple(nights))) / max(len(nights), 1))
        r["amenities"] = json.loads(r["amenities"] or "[]")
        if unit_type and unit_type != "Любой" and r["unit_type"] != unit_type:
            continue
        if guests and (r["capacity_adult"] + r["capacity_children"]) < guests:
            continue
        result.append(r)
    return sorted(result, key=lambda x: x["price"])


def day_load(day_iso: str) -> int:
    """Сколько домиков свободно на указанную дату."""
    return _one("SELECT COUNT(DISTINCT unit_id) c FROM availability"
                " WHERE day = ? AND is_free = 1", (day_iso,))["c"]


def unit_types() -> list[str]:
    return [r["unit_type"] for r in _rows(
        "SELECT DISTINCT unit_type FROM units WHERE active = 1 AND capacity_adult > 0")]


# --- брони -----------------------------------------------------------------
def insert_booking(guest_id: int, unit_id: int, date_in: str, date_out: str,
                   adults: int, children: int, wishes: str, source: str,
                   total: float, handled_by_bot: bool = True) -> int:
    return _exec(
        "INSERT INTO bookings (guest_id, unit_id, date_in, date_out, adults, children,"
        " wishes, source, total, handled_by_bot) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (guest_id, unit_id, date_in, date_out, adults, children,
         wishes, source, total, int(handled_by_bot)))


def mark_booked(unit_id: int, date_in: str, date_out: str) -> None:
    """Помечает ночи как занятые после подтверждения заявки (черновик пока нет)."""
    nights = [(date.fromisoformat(date_in) + timedelta(days=i)).isoformat()
              for i in range((date.fromisoformat(date_out) - date.fromisoformat(date_in)).days)]
    with _lock, _conn:
        for n in nights:
            _conn.execute("UPDATE availability SET is_free = 0 WHERE unit_id = ? AND day = ?",
                          (unit_id, n))


def set_booking_status(booking_id: int, status: str) -> dict | None:
    _exec("UPDATE bookings SET status = ?, confirmed_at = CASE WHEN ? = 'confirmed'"
          " THEN datetime('now') ELSE confirmed_at END WHERE id = ?",
          (status, status, booking_id))
    return get_booking(booking_id)


def get_booking(booking_id: int) -> dict | None:
    b = _one("""SELECT b.*, g.full_name, g.phone, g.tg_id, u.name AS unit_name
                FROM bookings b
                JOIN guests g ON g.id = b.guest_id
                LEFT JOIN units u ON u.id = b.unit_id
                WHERE b.id = ?""", (booking_id,))
    return b


def guest_bookings(tg_id: int) -> list[dict]:
    return _rows("""SELECT b.*, u.name AS unit_name FROM bookings b
                    JOIN guests g ON g.id = b.guest_id
                    LEFT JOIN units u ON u.id = b.unit_id
                    WHERE g.tg_id = ? ORDER BY b.created_at DESC LIMIT 10""", (tg_id,))


def recent_bookings(limit: int = 15) -> list[dict]:
    return _rows("""SELECT b.*, g.full_name, g.phone, u.name AS unit_name
                    FROM bookings b
                    JOIN guests g ON g.id = b.guest_id
                    LEFT JOIN units u ON u.id = b.unit_id
                    ORDER BY b.id DESC LIMIT ?""", (limit,))


# --- FAQ / услуги ----------------------------------------------------------
def faq_list() -> list[dict]:
    return _rows("SELECT slug, question FROM faq_articles WHERE is_active = 1 ORDER BY id")


def faq_get(slug: str) -> dict | None:
    return _one("SELECT * FROM faq_articles WHERE slug = ?", (slug,))


def services_list() -> list[dict]:
    return _rows("SELECT * FROM services WHERE active = 1 ORDER BY category, price")


# --- touchpoints / метрики -------------------------------------------------
def record_touchpoint(guest_id: int | None, channel: str, direction: str,
                      intent: str, text: str, answered_by: str = "bot",
                      booking_id: int | None = None) -> int:
    return _exec(
        "INSERT INTO touchpoints (guest_id, booking_id, channel, direction, intent, text,"
        " answered_by) VALUES (?,?,?,?,?,?,?)",
        (guest_id, booking_id, channel, direction, intent, text[:500], answered_by))


def metrics(days: int = 7) -> dict:
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    total = _one("SELECT COUNT(*) c FROM touchpoints WHERE created_at >= ?", (since,))["c"]
    auto = _one("SELECT COUNT(*) c FROM touchpoints WHERE created_at >= ?"
                " AND answered_by = 'bot'", (since,))["c"]
    bookings = _one("SELECT COUNT(*) c FROM bookings WHERE created_at >= ?", (since,))["c"]
    confirmed = _one("SELECT COUNT(*) c FROM bookings WHERE created_at >= ?"
                     " AND status IN ('confirmed','prepaid')", (since,))["c"]
    escal = _one("SELECT COUNT(*) c FROM touchpoints WHERE created_at >= ?"
                 " AND intent = 'escalation'", (since,))["c"]
    faq_hits = _one("SELECT COUNT(*) c FROM touchpoints WHERE created_at >= ?"
                    " AND intent = 'faq'", (since,))["c"]
    pending = _one("SELECT COUNT(*) c FROM bookings WHERE status = 'new'")["c"]
    sent_fu = _one("SELECT COUNT(*) c FROM followups WHERE status = 'sent'"
                   " AND sent_at >= ?", (since,))["c"]
    planned_fu = _one("SELECT COUNT(*) c FROM followups WHERE status = 'pending'")["c"]
    return {
        "period_days": days, "total_in": total, "auto": auto,
        "auto_share": round(auto * 100 / total, 1) if total else 0,
        "bookings": bookings, "confirmed": confirmed,
        "conversion": round(confirmed * 100 / bookings, 1) if bookings else 0,
        "escalations": escal, "faq_hits": faq_hits,
        "pending_confirm": pending,
        "followups_sent": sent_fu, "followups_planned": planned_fu,
    }


def due_followups(now_iso: str) -> list[dict]:
    return _rows("""SELECT id, kind, booking_id FROM followups
                    WHERE status = 'pending' AND scheduled_at <= ?""", (now_iso,))


def followup_done(followup_id: int) -> None:
    _exec("UPDATE followups SET status = 'sent', sent_at = datetime('now') WHERE id = ?",
          (followup_id,))


def schedule_followup(booking_id: int, kind: str, scheduled_at: str) -> None:
    _exec("INSERT INTO followups (booking_id, kind, scheduled_at) VALUES (?,?,?)",
          (booking_id, kind, scheduled_at))


def close_db() -> None:
    """Аккуратно закрывает соединение при остановке сервиса."""
    with _lock:
        _conn.close()
