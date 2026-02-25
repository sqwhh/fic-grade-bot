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
    if "invalid" in e and "password" in e:
        return "Invalid login or password."
    return err or ""


def short_person_name(full_name: str | None) -> str | None:
    """Return a short name for greetings (usually the first word)."""
    if not full_name:
        return None
    s = " ".join(full_name.split()).strip()
    if not s:
        return None
    return s.split(" ")[0]


# -----------------------------
# FIC term helpers (for Moodle UI)
# -----------------------------


def parse_fic_term_code(term_label: str | None) -> int:
    """Parse an integer term code from labels like 'FIC 202503'.

    Returns 0 if the term code is not present.
    """
    if not term_label:
        return 0
    s = " ".join(str(term_label).split()).upper()
    # Expect exactly 6 digits like 202503.
    import re

    m = re.search(r"\b(\d{6})\b", s)
    return int(m.group(1)) if m else 0


def current_fic_term_code(now: datetime | None = None) -> int:
    """Compute the current FIC term code as YYYYTT (TT is 01/02/03).

    Heuristic mapping (Vancouver time):
      - Jan–Apr  -> 01
      - May–Aug  -> 02
      - Sep–Dec  -> 03
    """
    try:
        tz_van = ZoneInfo("America/Vancouver")
    except Exception:
        tz_van = timezone.utc

    dt = now.astimezone(tz_van) if (now and now.tzinfo) else (now or datetime.now(tz_van))
    y = dt.year
    m = dt.month
    if 1 <= m <= 4:
        t = 1
    elif 5 <= m <= 8:
        t = 2
    else:
        t = 3
    return y * 100 + t


def fic_term_prev(term_code: int, steps: int = 1) -> int:
    """Return the previous FIC term code (YYYYTT) by N steps."""
    y = int(term_code) // 100
    t = int(term_code) % 100
    for _ in range(max(0, int(steps))):
        if t <= 1:
            y -= 1
            t = 3
        else:
            t -= 1
    return y * 100 + t


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
