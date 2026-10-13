"""Персистентное FSM-хранилище в SQLite.

Диалоги клиентов (даты, гости, пожелания...) переживают рестарт бота —
важно для прода: обновление версии не сбрасывает клиентов посреди квиза.
"""
import json
from typing import Any, Mapping

from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

import db


def _ks(key: StorageKey) -> str:
    return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id}:{key.destiny}"


class SQLiteStorage(BaseStorage):
    """Хранит state/data квиза в таблице fsm (см. db.py)."""

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        if state is None:
            s = None
        elif isinstance(state, str):
            s = state
        else:
            s = state.state  # объект State → "Booking:dates"
        db._exec(
            "INSERT INTO fsm (k, state) VALUES (?,?) "
            "ON CONFLICT(k) DO UPDATE SET state = excluded.state", (_ks(key), s))

    async def get_state(self, key: StorageKey) -> str | None:
        row = db._one("SELECT state FROM fsm WHERE k = ?", (_ks(key),))
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        db._exec(
            "INSERT INTO fsm (k, data) VALUES (?,?) "
            "ON CONFLICT(k) DO UPDATE SET data = excluded.data",
            (_ks(key), json.dumps(dict(data), ensure_ascii=False)))

    async def get_data(self, key: StorageKey) -> dict:
        row = db._one("SELECT data FROM fsm WHERE k = ?", (_ks(key),))
        if not row or not row["data"]:
            return {}
        return json.loads(row["data"])

    async def close(self) -> None:
        pass  # соединением владеет db.py
