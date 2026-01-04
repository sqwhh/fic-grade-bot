# monitoring.py
"""Background monitoring loops.

Only FIC monitoring is kept. Moodle monitoring was removed.
"""

import asyncio
import contextlib
import time
from typing import Dict

import aiosqlite
from aiogram import Bot

from config import fernet, CHECK_INTERVAL_SEC, NOTIF_DURATION_DAYS, NOTIF_WARN_BEFORE_DAYS
import database as db
import messages
from grades_service import GradesService
from playwright_manager import get_playwright_instance
from utils import normalize_snapshot, compute_hash, _localize_known_error


# Global task registry to manage running monitors
fic_monitor_tasks: Dict[int, asyncio.Task] = {}


async def _enforce_fic_expiry(bot: Bot, user_id: int, user: dict) -> bool:
    """Return True if notifications are still active, otherwise disable and notify user."""
    # Ensure expiry timestamp exists (for users from older DBs).
    if user.get("fic_active") and not user.get("fic_active_until"):
        await db.ensure_fic_until_set(user_id)
        user = await db.get_user(user_id) or user

    until_ts = user.get("fic_active_until")
    if not until_ts:
        # Should not happen for new DBs, but keep the bot resilient.
        return True

    now = int(time.time())
    remaining = int(until_ts) - now

    # Expired -> auto disable
    if remaining <= 0:
        await db.set_fic_active(user_id, False)
        await bot.send_message(
            user_id,
            "🔕 <b>Notifications turned off automatically.</b>\n\n"
            f"Notifications can stay enabled for <b>{NOTIF_DURATION_DAYS} days</b> only. "
            "You can enable them again in Settings.",
            parse_mode="HTML",
        )
        return False

    # Warn before expiry (default: 1 day)
    warn_window = max(0, int(NOTIF_WARN_BEFORE_DAYS)) * 86400
    if warn_window > 0 and remaining <= warn_window and not bool(user.get("fic_warned") or 0):
        # Days left, shown as 1 when under 24h remains.
        days_left = db.fic_notif_days_left(user) or 0
        await bot.send_message(
            user_id,
            "⏳ <b>Reminder</b>\n\n"
            f"Notifications will be turned off in <b>{days_left}</b> day{'s' if days_left != 1 else ''}.\n"
            f"(They can stay enabled for <b>{NOTIF_DURATION_DAYS} days</b> only.)",
            parse_mode="HTML",
        )
        await db.set_fic_warned(user_id, True)

    return True


async def monitor_fic_loop(bot: Bot, user_id: int) -> None:
    # Fast path: if notifications are already off/expired, do not spin up Playwright.
    user = await db.get_user(user_id)
    if not user or not bool(user.get("fic_active", 0)):
        return
    if not await _enforce_fic_expiry(bot, user_id, user):
        return

    shared_pw = await get_playwright_instance()
    svc = GradesService(shared_pw=shared_pw)

    try:
        while True:
            user = await db.get_user(user_id)
            if not user or not bool(user.get("fic_active", 0)):
                break

            # Auto-off & warning logic
            if not await _enforce_fic_expiry(bot, user_id, user):
                break

            login = fernet.decrypt(user["login_enc"]).decode()
            password = fernet.decrypt(user["password_enc"]).decode()

            try:
                grades_map = await svc.fic_final_grades(login, password)
                await db.set_fic_error(user_id, None)
            except Exception as e:
                await db.set_fic_error(user_id, _localize_known_error(str(e)))
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue

            snapshot_json = normalize_snapshot(grades_map)
            h = compute_hash(snapshot_json)
            state = await db.get_fic_state(user_id)
            last_hash = state.get("last_hash")

            if not last_hash:
                await db.update_fic_snapshot(user_id, snapshot_json, h)
            elif h != last_hash:
                changes = messages.find_new_or_changed_fic_grades(
                    state.get("last_snapshot"),
                    grades_map,
                )
                await db.update_fic_snapshot(user_id, snapshot_json, h)
                if changes:
                    msg = messages.format_fic_new_grade_notification(changes)
                    await bot.send_message(user_id, msg, parse_mode="HTML")

            await asyncio.sleep(CHECK_INTERVAL_SEC)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        await db.set_fic_error(user_id, f"Monitor error: {e}")
    finally:
        try:
            await svc.close()
        except Exception:
            # Playwright may already be closed during shutdown.
            pass
        fic_monitor_tasks.pop(user_id, None)


def ensure_fic_task(bot: Bot, user_id: int) -> None:
    """Start (or keep) a running monitoring task for the user."""
    if user_id in fic_monitor_tasks and not fic_monitor_tasks[user_id].done():
        return
    fic_monitor_tasks[user_id] = asyncio.create_task(monitor_fic_loop(bot, user_id))


async def resume_tasks_on_start(bot: Bot) -> None:
    """On bot startup, restore monitoring tasks for users who have it enabled."""
    async with db.get_db() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT user_id, fic_active FROM users") as cur:
            async for row in cur:
                if row["fic_active"]:
                    ensure_fic_task(bot, row["user_id"])


async def cancel_task_safely(t: asyncio.Task | None) -> None:
    if t and not t.done():
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
