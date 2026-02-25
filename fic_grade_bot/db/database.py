# database.py
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import time
import math
import json
from pathlib import Path

import aiosqlite

from ..config import (
    DB_PATH,
    fernet,
    NOTIF_DURATION_DAYS,
    MOODLE_NOTIF_DURATION_DAYS,
    MOODLE_NOTIF_MAX_DAYS,
)

# ====== SCHEMA ======

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    display_name  TEXT,
    is_demo       INTEGER NOT NULL DEFAULT 0,
    login_enc     BLOB    NOT NULL,
    password_enc  BLOB    NOT NULL,
    fic_active    INTEGER NOT NULL DEFAULT 1,
    fic_active_until INTEGER,
    fic_warned    INTEGER NOT NULL DEFAULT 0,
    moodle_active    INTEGER NOT NULL DEFAULT 1,
    moodle_active_until INTEGER,
    moodle_warned    INTEGER NOT NULL DEFAULT 0,
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


CREATE_MOODLE_STATE = """
CREATE TABLE IF NOT EXISTS moodle_state (
    user_id       INTEGER PRIMARY KEY,
    last_hash     TEXT,
    last_snapshot TEXT,
    updated_at    TEXT,
    last_error    TEXT,
    last_changes  TEXT,
    last_changes_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
"""


# ====== CONNECTION HELPERS ======

@asynccontextmanager
async def get_db():
    # Create parent folder for local relative DB paths like "./data/bot.db".
    # (If DB_PATH is an unwritable absolute path like "/data/bot.db" on macOS,
    # the connect will still fail with a helpful error below.)
    p = Path(DB_PATH)
    if str(p.parent) not in (".", ""):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    try:
        db = await aiosqlite.connect(DB_PATH)
    except Exception as e:
        raise RuntimeError(
            f"Cannot open database file at DB_PATH={DB_PATH!r}. "
            f"If you run locally, set DB_PATH to a writable path like 'bot.db' or './data/bot.db' "
            f"(and make sure the folder exists)."
        ) from e
    await db.execute("PRAGMA foreign_keys=ON;")
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    async with get_db() as db:
        await db.execute(CREATE_USERS)
        await db.execute(CREATE_FIC_STATE)
        await db.execute(CREATE_MOODLE_STATE)

        # --- lightweight migrations for existing DBs ---
        cur = await db.execute("PRAGMA table_info(users)")
        cols = {row[1] async for row in cur}  # row[1] = column name

        if "display_name" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN display_name TEXT")

        if "is_demo" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")

        if "fic_active_until" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN fic_active_until INTEGER")
        if "fic_warned" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN fic_warned INTEGER NOT NULL DEFAULT 0")

        if "moodle_active" not in cols:
            # Moodle notifications are enabled by default.
            await db.execute("ALTER TABLE users ADD COLUMN moodle_active INTEGER NOT NULL DEFAULT 1")
        if "moodle_active_until" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN moodle_active_until INTEGER")
        if "moodle_warned" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN moodle_warned INTEGER NOT NULL DEFAULT 0")

        # For older DBs (or users created before Moodle notifications existed),
        # ensure Moodle notifications are enabled by default.
        now_ts = int(time.time())
        moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
        moodle_until = now_ts + moodle_days * 86400
        await db.execute(
            """
            UPDATE users
            SET moodle_active=1,
                moodle_active_until=COALESCE(moodle_active_until, ?),
                moodle_warned=0,
                updated_at=?
            WHERE is_demo=0 AND (moodle_active IS NULL OR moodle_active=0)
            """,
            (moodle_until, datetime.now(timezone.utc).isoformat()),
        )
        # Moodle state migrations
        cur2 = await db.execute("PRAGMA table_info(moodle_state)")
        moodle_cols = {row[1] async for row in cur2}
        if "last_changes" not in moodle_cols:
            await db.execute("ALTER TABLE moodle_state ADD COLUMN last_changes TEXT")
        if "last_changes_at" not in moodle_cols:
            await db.execute("ALTER TABLE moodle_state ADD COLUMN last_changes_at TEXT")

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
    fic_until_ts = now_ts + NOTIF_DURATION_DAYS * 86400
    moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
    moodle_until_ts = now_ts + moodle_days * 86400

    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users (
                user_id, login_enc, password_enc, is_demo,
                fic_active, fic_active_until, fic_warned,
                moodle_active, moodle_active_until, moodle_warned,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 0, 1, ?, 0, 1, ?, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                login_enc=excluded.login_enc,
                password_enc=excluded.password_enc,
                is_demo=excluded.is_demo,
                fic_active=excluded.fic_active,
                fic_active_until=excluded.fic_active_until,
                fic_warned=excluded.fic_warned,
                moodle_active=excluded.moodle_active,
                moodle_active_until=excluded.moodle_active_until,
                moodle_warned=excluded.moodle_warned,
                updated_at=excluded.updated_at
            """,
            (user_id, login_enc, password_enc, fic_until_ts, moodle_until_ts, now, now),
        )
        await db.commit()


async def create_demo_user(user_id: int, *, display_name: str = "Demo Student") -> None:
    """Create (or overwrite) a demo user record.

    The demo profile does not use real credentials and should never attempt to
    sign in to the real portals. It exists to showcase the UI and notification
    flow.
    """
    now = datetime.now(timezone.utc).isoformat()
    now_ts = int(time.time())

    login_enc = fernet.encrypt(b"demo")
    password_enc = fernet.encrypt(b"demo")

    fic_until_ts = now_ts + NOTIF_DURATION_DAYS * 86400
    moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
    moodle_until_ts = now_ts + moodle_days * 86400

    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users (
                user_id, display_name, is_demo,
                login_enc, password_enc,
                fic_active, fic_active_until, fic_warned,
                moodle_active, moodle_active_until, moodle_warned,
                created_at, updated_at
            )
            VALUES (?, ?, 1, ?, ?, 1, ?, 0, 1, ?, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name,
                is_demo=excluded.is_demo,
                login_enc=excluded.login_enc,
                password_enc=excluded.password_enc,
                fic_active=excluded.fic_active,
                fic_active_until=excluded.fic_active_until,
                fic_warned=excluded.fic_warned,
                moodle_active=excluded.moodle_active,
                moodle_active_until=excluded.moodle_active_until,
                moodle_warned=excluded.moodle_warned,
                updated_at=excluded.updated_at
            """,
            (user_id, display_name, login_enc, password_enc, fic_until_ts, moodle_until_ts, now, now),
        )
        await db.commit()


async def set_display_name(user_id: int, display_name: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET display_name = ?, updated_at = ? WHERE user_id = ?",
            (display_name, now, user_id),
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
        await db.execute("DELETE FROM moodle_state WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        await db.commit()


# ====== FIC STATE ======

async def get_fic_state(user_id: int) -> dict:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM fic_state WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else {}


async def get_moodle_state(user_id: int) -> dict:
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM moodle_state WHERE user_id=?", (user_id,))
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


async def update_moodle_snapshot(user_id: int, snapshot_json: str, h: str, *, recent_events: list[dict] | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    last_changes = None
    last_changes_at = None

    # Optionally record recent item changes (newest-first, trimmed).
    if recent_events is not None:
        async with get_db() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT last_changes FROM moodle_state WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            existing: list[dict] = []
            if row and row["last_changes"]:
                try:
                    existing = json.loads(row["last_changes"]) or []
                except Exception:
                    existing = []
            merged = list(recent_events) + list(existing)
            merged = merged[:50]
            last_changes = json.dumps(merged, ensure_ascii=False)
            last_changes_at = now

    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO moodle_state (user_id, last_snapshot, last_hash, updated_at, last_error, last_changes, last_changes_at)
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                last_snapshot=excluded.last_snapshot,
                last_hash=excluded.last_hash,
                updated_at=excluded.updated_at,
                last_error=NULL,
                last_changes=COALESCE(excluded.last_changes, moodle_state.last_changes),
                last_changes_at=COALESCE(excluded.last_changes_at, moodle_state.last_changes_at)
            """,
            (user_id, snapshot_json, h, now, last_changes, last_changes_at),
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


async def set_moodle_error(user_id: int, err: Optional[str]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO moodle_state (user_id, last_error, updated_at)
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


def moodle_notif_days_left(rec: dict | None) -> int | None:
    if not rec or not rec.get("moodle_active"):
        return None
    return _days_left_from_until(rec.get("moodle_active_until"))


async def set_moodle_active(user_id: int, active: bool) -> None:
    """Enable/disable Moodle monitoring + notifications.

    When enabling, it is enabled for NOTIF_DURATION_DAYS and
    will auto-disable afterwards.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = int(time.time())

    moodle_active = 1 if active else 0
    # Moodle has its own duration and a hard cap.
    moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
    until_ts = (now_ts + moodle_days * 86400) if active else None
    warned = 0

    async with get_db() as db:
        await db.execute(
            "UPDATE users SET moodle_active=?, moodle_active_until=?, moodle_warned=?, updated_at=? WHERE user_id=?",
            (moodle_active, until_ts, warned, now_iso, user_id),
        )
        await db.commit()


async def set_moodle_warned(user_id: int, warned: bool) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET moodle_warned=?, updated_at=? WHERE user_id=?",
            (1 if warned else 0, datetime.now(timezone.utc).isoformat(), user_id),
        )
        await db.commit()


async def ensure_moodle_until_set(user_id: int) -> None:
    """If Moodle notifications are ON but no expiry timestamp (older DB), set it."""
    rec = await get_user(user_id)
    if not rec or not bool(rec.get("moodle_active")):
        return
    if rec.get("moodle_active_until"):
        return
    now_ts = int(time.time())
    moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
    until_ts = now_ts + moodle_days * 86400
    async with get_db() as db:
        await db.execute(
            "UPDATE users SET moodle_active_until=?, moodle_warned=0, updated_at=? WHERE user_id=?",
            (until_ts, datetime.now(timezone.utc).isoformat(), user_id),
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
