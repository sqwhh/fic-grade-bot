# database.py
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import time
import math

import aiosqlite

from config import DB_PATH, fernet, NOTIF_DURATION_DAYS

# ====== SCHEMA ======

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    login_enc     BLOB    NOT NULL,
    password_enc  BLOB    NOT NULL,
    fic_active    INTEGER NOT NULL DEFAULT 1,
    fic_active_until INTEGER,
    fic_warned    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
"""

CREATE_FIC_STATE = """
CREATE TABLE IF NOT EXISTS fic_state (
    user_id       INTEGER PRIMARY KEY,
    last_hash     TEXT,
    last_snapshot TEXT,
    updated_at    TEXT,
    last_error    TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
"""


# ====== CONNECTION HELPERS ======

@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA foreign_keys=ON;")
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    async with get_db() as db:
        await db.execute(CREATE_USERS)
        await db.execute(CREATE_FIC_STATE)

        # --- lightweight migrations for existing DBs ---
        cur = await db.execute("PRAGMA table_info(users)")
        cols = {row[1] async for row in cur}  # row[1] = column name

        if "fic_active_until" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN fic_active_until INTEGER")
        if "fic_warned" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN fic_warned INTEGER NOT NULL DEFAULT 0")
        await db.commit()


def _days_left_from_until(until_ts: int | None) -> int | None:
    """Return whole days left until unix timestamp (ceil)."""
    if not until_ts:
        return None
    now = int(time.time())
    sec = until_ts - now
    return max(0, int(math.ceil(sec / 86400)))


# ====== USER CREDENTIALS ======

async def save_credentials(user_id: int, login: str, password: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    now_ts = int(time.time())
    login_enc = fernet.encrypt(login.encode())
    password_enc = fernet.encrypt(password.encode())
    until_ts = now_ts + NOTIF_DURATION_DAYS * 86400

    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users (user_id, login_enc, password_enc, fic_active, fic_active_until, fic_warned, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                login_enc=excluded.login_enc,
                password_enc=excluded.password_enc,
                fic_active=excluded.fic_active,
                fic_active_until=excluded.fic_active_until,
                fic_warned=excluded.fic_warned,
                updated_at=excluded.updated_at
            """,
            (user_id, login_enc, password_enc, until_ts, now, now),
        )
        await db.commit()


async def get_user(user_id: int) -> Optional[dict]:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


def fic_notif_days_left(rec: dict | None) -> int | None:
    if not rec or not rec.get("fic_active"):
        return None
    return _days_left_from_until(rec.get("fic_active_until"))


async def delete_user_data(user_id: int) -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM fic_state WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        await db.commit()


# ====== FIC STATE ======

async def get_fic_state(user_id: int) -> dict:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM fic_state WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else {}


async def update_fic_snapshot(user_id: int, snapshot_json: str, h: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO fic_state (user_id, last_snapshot, last_hash, updated_at, last_error)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                last_snapshot=excluded.last_snapshot,
                last_hash=excluded.last_hash,
                updated_at=excluded.updated_at,
                last_error=NULL
            """,
            (user_id, snapshot_json, h, now),
        )
        await db.commit()


async def set_fic_error(user_id: int, err: Optional[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO fic_state (user_id, last_error, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (user_id, err, now),
        )
        await db.commit()


# ====== MONITORING TOGGLES ======

async def set_fic_active(user_id: int, active: bool) -> None:
    """Enable/disable FIC notifications.

    When enabling, notifications are enabled for NOTIF_DURATION_DAYS and
    will auto-disable afterwards.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = int(time.time())

    fic_active = 1 if active else 0
    until_ts = (now_ts + NOTIF_DURATION_DAYS * 86400) if active else None
    warned = 0

    async with get_db() as db:
        await db.execute(
            "UPDATE users SET fic_active=?, fic_active_until=?, fic_warned=?, updated_at=? WHERE user_id=?",
            (fic_active, until_ts, warned, now_iso, user_id),
        )
        await db.commit()


async def set_fic_warned(user_id: int, warned: bool) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET fic_warned=?, updated_at=? WHERE user_id=?",
            (1 if warned else 0, datetime.now(timezone.utc).isoformat(), user_id),
        )
        await db.commit()


async def ensure_fic_until_set(user_id: int) -> None:
    """If user has notifications ON but no expiry timestamp (older DB), set it."""
    rec = await get_user(user_id)
    if not rec or not bool(rec.get("fic_active")):
        return
    if rec.get("fic_active_until"):
        return
    now_ts = int(time.time())
    until_ts = now_ts + NOTIF_DURATION_DAYS * 86400
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET fic_active_until=?, fic_warned=0, updated_at=? WHERE user_id=?",
            (until_ts, datetime.now(timezone.utc).isoformat(), user_id),
        )
        await db.commit()
