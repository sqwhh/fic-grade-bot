# utils.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_snapshot(obj: dict) -> str:
    """Stable JSON serialization for hashing/storage."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_snapshot(snapshot_json: Optional[str]) -> dict:
    if not snapshot_json:
        return {}
    try:
        return json.loads(snapshot_json)
    except Exception:
        return {}


def format_dt_vancouver(iso_dt: str | None) -> str:
    """Format an ISO UTC timestamp in Vancouver time."""
    if not iso_dt:
        return "—"
    try:
        s = iso_dt.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"

        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        tz_van = ZoneInfo("America/Vancouver")
        dt_van = dt.astimezone(tz_van)

        today = datetime.now(tz_van).date()
        d = dt_van.date()

        if d == today:
            return f"today {dt_van:%H:%M:%S}"
        if d == (today - timedelta(days=1)):
            return f"yesterday {dt_van:%H:%M:%S}"
        return dt_van.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return "—"


def _short_err(err: str, limit: int = 220) -> str:
    if not err:
        return ""
    s = " ".join(err.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _localize_known_error(err: str) -> str:
    e = (err or "").lower()
    if ("invalid" in e and "password" in e) or ("неверный логин" in e):
        return "Invalid login or password."
    return err or ""


async def safe_edit(
    message: Message,
    *,
    text: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool | None = True,
):
    """Edit a message safely (ignore 'message is not modified', handle too-long text)."""
    try:
        if text is not None:
            return await message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        return await message.edit_reply_markup(reply_markup=reply_markup)

    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return None

        if "message is too long" in msg and text is not None:
            await message.answer(
                text,
                reply_markup=None,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            try:
                return await message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest:
                return None

        raise
