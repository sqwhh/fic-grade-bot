# monitoring.py
"""Background monitoring loops.

Monitors:
- FIC final grades (learning.fraseric.ca)
- Moodle overview grades (moodle.fraseric.ca)
"""

import asyncio
import contextlib
import time
from datetime import datetime, timezone
from typing import Dict

import aiosqlite
from aiogram import Bot

from ..config import (
    fernet,
    CHECK_INTERVAL_SEC,
    MOODLE_CHECK_INTERVAL_SEC,
    NOTIF_DURATION_DAYS,
    NOTIF_WARN_BEFORE_DAYS,
    MOODLE_NOTIF_DURATION_DAYS,
    MOODLE_NOTIF_MAX_DAYS,
    MOODLE_NOTIF_WARN_BEFORE_DAYS,
)
from ..db import database as db
from ..telegram import messages
from ..services.grades_service import GradesService
from ..browser.playwright_manager import get_playwright_instance
from ..utils import normalize_snapshot, compute_hash, _localize_known_error


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


async def _enforce_moodle_expiry(bot: Bot, user_id: int, user: dict) -> bool:
    """Return True if notifications are still active, otherwise disable and notify user."""
    if user.get("moodle_active") and not user.get("moodle_active_until"):
        await db.ensure_moodle_until_set(user_id)
        user = await db.get_user(user_id) or user

    until_ts = user.get("moodle_active_until")
    if not until_ts:
        return True

    now = int(time.time())
    remaining = int(until_ts) - now

    if remaining <= 0:
        await db.set_moodle_active(user_id, False)
        moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
        await bot.send_message(
            user_id,
            "🔕 <b>Moodle notifications turned off automatically.</b>\n\n"
            f"Notifications can stay enabled for <b>{moodle_days} days</b> only. "
            "You can enable them again in Settings.",
            parse_mode="HTML",
        )
        return False

    warn_window = max(0, int(MOODLE_NOTIF_WARN_BEFORE_DAYS)) * 86400
    if warn_window > 0 and remaining <= warn_window and not bool(user.get("moodle_warned") or 0):
        days_left = db.moodle_notif_days_left(user) or 0
        moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
        await bot.send_message(
            user_id,
            "⏳ <b>Reminder (Moodle)</b>\n\n"
            f"Notifications will be turned off in <b>{days_left}</b> day{'s' if days_left != 1 else ''}.\n"
            f"(They can stay enabled for <b>{moodle_days} days</b> only.)",
            parse_mode="HTML",
        )
        await db.set_moodle_warned(user_id, True)

    return True


async def monitor_fic_loop(bot: Bot, user_id: int) -> None:
    # Fast path: if notifications are already off/expired, do not spin up Playwright.
    user = await db.get_user(user_id)
    if not user or (not bool(user.get("fic_active", 0)) and not bool(user.get("moodle_active", 0))):
        return

    # Demo users do not run real monitoring loops.
    if bool(user.get("is_demo")):
        return
    if user.get("fic_active") and not await _enforce_fic_expiry(bot, user_id, user):
        return
    if user.get("moodle_active") and not await _enforce_moodle_expiry(bot, user_id, user):
        return

    shared_pw = await get_playwright_instance()
    svc = GradesService(shared_pw=shared_pw)

    next_fic_ts = 0.0
    next_moodle_ts = 0.0

    try:
        while True:
            user = await db.get_user(user_id)
            if not user or (not bool(user.get("fic_active", 0)) and not bool(user.get("moodle_active", 0))):
                break

            # Auto-off & warning logic
            if user.get("fic_active") and not await _enforce_fic_expiry(bot, user_id, user):
                # After expiry we may still keep the loop running for Moodle.
                user = await db.get_user(user_id) or user
            if user.get("moodle_active") and not await _enforce_moodle_expiry(bot, user_id, user):
                user = await db.get_user(user_id) or user

            # If both are now off, stop.
            if not bool(user.get("fic_active", 0)) and not bool(user.get("moodle_active", 0)):
                break

            login = fernet.decrypt(user["login_enc"]).decode()
            password = fernet.decrypt(user["password_enc"]).decode()

            now = time.time()

            # --- FIC ---
            if bool(user.get("fic_active", 0)) and now >= next_fic_ts:
                try:
                    grades_map = await svc.fic_final_grades(login, password)
                    await db.set_fic_error(user_id, None)

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

                except Exception as e:
                    await db.set_fic_error(user_id, _localize_known_error(str(e)))
                finally:
                    next_fic_ts = now + max(5, int(CHECK_INTERVAL_SEC))

            # --- Moodle ---
            if bool(user.get("moodle_active", 0)) and now >= next_moodle_ts:
                try:
                    moodle_snapshot = await svc.moodle_full_snapshot(login, password)
                    await db.set_moodle_error(user_id, None)

                    snapshot_json = normalize_snapshot(moodle_snapshot)
                    h = compute_hash(snapshot_json)
                    state = await db.get_moodle_state(user_id)
                    last_hash = state.get("last_hash")

                    if not last_hash:
                        await db.update_moodle_snapshot(user_id, snapshot_json, h)
                    elif h != last_hash:
                        changes = messages.find_new_or_changed_moodle_items(
                            state.get("last_snapshot"),
                            moodle_snapshot,
                        )
                        # Store compact recent events for the UI.
                        now_iso = datetime.now(timezone.utc).isoformat()
                        events = messages.compress_moodle_changes_for_recent(changes, now_iso=now_iso)
                        await db.update_moodle_snapshot(user_id, snapshot_json, h, recent_events=events)
                        if changes:
                            msg = messages.format_moodle_item_change_notification(changes)
                            await bot.send_message(user_id, msg, parse_mode="HTML")

                except Exception as e:
                    await db.set_moodle_error(user_id, _localize_known_error(str(e)))

                finally:
                    next_moodle_ts = now + max(5, int(MOODLE_CHECK_INTERVAL_SEC))

            # Sleep until the next due check (either FIC or Moodle).
            # If one source is off, keep its next_ts far in the future.
            now2 = time.time()
            n1 = next_fic_ts if bool(user.get("fic_active", 0)) else (now2 + 10**9)
            n2 = next_moodle_ts if bool(user.get("moodle_active", 0)) else (now2 + 10**9)
            sleep_for = max(1.0, min(n1, n2) - now2)
            await asyncio.sleep(sleep_for)

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
        async with conn.execute("SELECT user_id, fic_active, moodle_active, is_demo FROM users") as cur:
            async for row in cur:
                if (row["fic_active"] or row["moodle_active"]) and not bool(row["is_demo"]):
                    ensure_fic_task(bot, row["user_id"])


async def cancel_task_safely(t: asyncio.Task | None) -> None:
    if t and not t.done():
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
