# demo.py
"""Demo / test profile.

The demo profile lets users explore all bot capabilities without providing
real credentials. It creates a local demo user record, seeds sample grades for
both sources (FIC + Moodle), and schedules two short demo notifications:

- After 3 minutes: a "new" FIC grade
- After 5 minutes: a "new" Moodle grade

These notifications are simulated and do not require network access.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery

from ...db import database as db
from .. import keyboards
from .. import messages
from ...utils import safe_edit, normalize_snapshot, compute_hash

router = Router()

# In-memory demo notification tasks (best-effort; reset/stop cancels them).
_demo_tasks: Dict[int, List[asyncio.Task]] = {}


# Sample grades used by the demo account.
DEMO_FIC_INITIAL = {
    "Fall 2025": {
        "CMPT130": "B+",
        "MATH151": "A-",
    },
    "Spring 2026": {
        "CMPT135": "",
        "HIST102": "",
    },
}

DEMO_FIC_UPDATED = {
    "Fall 2025": {
        "CMPT130": "B+",
        "MATH151": "A-",
    },
    "Spring 2026": {
        "CMPT135": "A",
        "HIST102": "",
    },
}

DEMO_MOODLE_INITIAL = {
    "courses": [
        {
            "course_id": 4841,
            "name": "FIC 202503 MACMT_YWELDESEL Discrete Mathematics Tutorial",
            "url": "https://moodle.fraseric.ca/course/user.php?mode=grade&id=4841&user=0",
            "grade_overview": "",
            "archived": False,
            "term_label": "FIC 202503",
            "course_code": "MACMT",
            "items": [
                {
                    "item_id": "row_demo1",
                    "name": "Quiz 1",
                    "grade": "",
                    "range": "0–100",
                    "percentage": "",
                    "feedback": "",
                    "link": None,
                    "level": 3,
                    "category_path": "Quizzes",
                },
                {
                    "item_id": "row_demo2",
                    "name": "Quiz 2",
                    "grade": "",
                    "range": "0–100",
                    "percentage": "",
                    "feedback": "",
                    "link": None,
                    "level": 3,
                    "category_path": "Quizzes",
                },
            ],
            "error": None,
        },
        {
            "course_id": 4529,
            "name": "FIC 202501 CMPT130_YWELDESEL (archived) Intro to Computer Programming 1 (archived)",
            "url": "https://moodle.fraseric.ca/course/user.php?mode=grade&id=4529&user=0",
            "grade_overview": "85% (A-)",
            "archived": True,
            "term_label": "FIC 202501",
            "course_code": "CMPT130",
            "items": [
                {
                    "item_id": "row_demo3",
                    "name": "Quiz 1",
                    "grade": "",
                    "range": "0–100",
                    "percentage": "85.00 %",
                    "feedback": "",
                    "link": None,
                    "level": 3,
                    "category_path": "Quizzes",
                }
            ],
            "error": None,
        },
    ],
    "fetched_at": None,
}

DEMO_MOODLE_UPDATED = {
    "courses": [
        {
            "course_id": 4841,
            "name": "FIC 202503 MACMT_YWELDESEL Discrete Mathematics Tutorial",
            "url": "https://moodle.fraseric.ca/course/user.php?mode=grade&id=4841&user=0",
            "grade_overview": "",
            "archived": False,
            "term_label": "FIC 202503",
            "course_code": "MACMT",
            "items": [
                {
                    "item_id": "row_demo1",
                    "name": "Quiz 1",
                    "grade": "",
                    "range": "0–100",
                    "percentage": "92.00 %",
                    "feedback": "Great improvement!",
                    "link": None,
                    "level": 3,
                    "category_path": "Quizzes",
                },
                {
                    "item_id": "row_demo2",
                    "name": "Quiz 2",
                    "grade": "",
                    "range": "0–100",
                    "percentage": "",
                    "feedback": "",
                    "link": None,
                    "level": 3,
                    "category_path": "Quizzes",
                },
                {
                    "item_id": "row_demo4",
                    "name": "Homework 1",
                    "grade": "",
                    "range": "0–10",
                    "percentage": "100.00 %",
                    "feedback": "Perfect.",
                    "link": None,
                    "level": 3,
                    "category_path": "Assignments",
                },
            ],
            "error": None,
        },
        {
            "course_id": 4529,
            "name": "FIC 202501 CMPT130_YWELDESEL (archived) Intro to Computer Programming 1 (archived)",
            "url": "https://moodle.fraseric.ca/course/user.php?mode=grade&id=4529&user=0",
            "grade_overview": "85% (A-)",
            "archived": True,
            "term_label": "FIC 202501",
            "course_code": "CMPT130",
            "items": [
                {
                    "item_id": "row_demo3",
                    "name": "Quiz 1",
                    "grade": "",
                    "range": "0–100",
                    "percentage": "85.00 %",
                    "feedback": "Nice work! (new comment)",
                    "link": None,
                    "level": 3,
                    "category_path": "Quizzes",
                }
            ],
            "error": None,
        },
    ],
    "fetched_at": None,
}


async def cancel_demo_tasks(user_id: int) -> None:
    """Cancel pending demo notification tasks for the user."""
    tasks = _demo_tasks.pop(user_id, [])
    for t in tasks:
        if not t.done():
            t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _track_task(user_id: int, t: asyncio.Task) -> None:
    _demo_tasks.setdefault(user_id, []).append(t)


async def _send_demo_fic_notification(bot: Bot, user_id: int) -> None:
    await asyncio.sleep(180)

    rec = await db.get_user(user_id)
    if not rec or not bool(rec.get("is_demo")) or not bool(rec.get("fic_active")):
        return

    st = await db.get_fic_state(user_id)
    changes = messages.find_new_or_changed_fic_grades(st.get("last_snapshot"), DEMO_FIC_UPDATED)

    snap = normalize_snapshot(DEMO_FIC_UPDATED)
    h = compute_hash(snap)
    await db.update_fic_snapshot(user_id, snap, h)

    if changes:
        await bot.send_message(user_id, messages.format_fic_new_grade_notification(changes), parse_mode="HTML")


async def _send_demo_moodle_notification(bot: Bot, user_id: int) -> None:
    await asyncio.sleep(300)

    rec = await db.get_user(user_id)
    if not rec or not bool(rec.get("is_demo")) or not bool(rec.get("moodle_active")):
        return

    st = await db.get_moodle_state(user_id)
    changes = messages.find_new_or_changed_moodle_items(st.get("last_snapshot"), DEMO_MOODLE_UPDATED)

    snap = normalize_snapshot(DEMO_MOODLE_UPDATED)
    h = compute_hash(snap)
    now_iso = datetime.now(timezone.utc).isoformat()
    events = messages.compress_moodle_changes_for_recent(changes, now_iso=now_iso)
    await db.update_moodle_snapshot(user_id, snap, h, recent_events=events)

    if changes:
        await bot.send_message(user_id, messages.format_moodle_item_change_notification(changes), parse_mode="HTML")


async def schedule_demo_notifications(bot: Bot, user_id: int) -> None:
    """Schedule (or reschedule) demo notifications."""
    await cancel_demo_tasks(user_id)
    _track_task(user_id, asyncio.create_task(_send_demo_fic_notification(bot, user_id)))
    _track_task(user_id, asyncio.create_task(_send_demo_moodle_notification(bot, user_id)))


@router.callback_query(F.data == "demo:start")
async def cb_demo_start(callback: CallbackQuery, bot: Bot):
    """Start the demo profile for a new user."""
    await callback.answer()
    uid = callback.from_user.id

    existing = await db.get_user(uid)
    if existing:
        await safe_edit(
            callback.message,
            text=(
                "🧪 <b>Test profile</b>\n\n"
                "You are already registered.\n\n"
                "If you want to try the demo profile, go to <b>Settings → Reset all</b> first."
            ),
            reply_markup=keyboards.kb_main_menu(),
        )
        return

    # Create demo user and seed snapshots.
    await db.create_demo_user(uid, display_name="Demo Student")

    fic_snap = normalize_snapshot(DEMO_FIC_INITIAL)
    await db.update_fic_snapshot(uid, fic_snap, compute_hash(fic_snap))

    moodle_snap = normalize_snapshot(DEMO_MOODLE_INITIAL)
    await db.update_moodle_snapshot(uid, moodle_snap, compute_hash(moodle_snap))

    await schedule_demo_notifications(bot, uid)

    await safe_edit(
        callback.message,
        text=(
            "✅ <b>Signed in to the demo profile.</b>\n\n"
            "Explore the bot features:\n"
            " • <b>My Grades</b> → FIC grades / Moodle grades\n"
            " • <b>FIC grades</b> → Calculate GPA\n"
            " • <b>Settings</b> → Notifications / Reset\n\n"
            "🔔 Demo notifications:\n"
            " • In <b>3 minutes</b> you will receive a demo <b>FIC</b> grade update.\n"
            " • In <b>5 minutes</b> you will receive a demo <b>Moodle</b> grade update."
        ),
        reply_markup=keyboards.kb_main_menu(),
    )
