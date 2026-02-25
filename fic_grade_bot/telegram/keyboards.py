# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from ..config import NOTIF_DURATION_DAYS, MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS


def kb_start_new_user() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Register", callback_data="reg:start")],
            [InlineKeyboardButton(text="🧪 Test profile (demo)", callback_data="demo:start")],
        ]
    )


def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 My Grades", callback_data="menu:mygrades")],
            [InlineKeyboardButton(text="⚙️ Settings", callback_data="menu:settings")],
        ]
    )


def kb_my_grades_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📗 FIC grades", callback_data="menu:fic_grades")],
            [InlineKeyboardButton(text="📙 Moodle grades", callback_data="menu:moodle_grades")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back:main")],
        ]
    )


def kb_fic_grades_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Calculate GPA", callback_data="grades:gpa_cached")],
            [InlineKeyboardButton(text="🔄 Force refresh", callback_data="grades:force_refresh")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back:mygrades")],
        ]
    )


def kb_moodle_grades_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📌 Active courses", callback_data="moodle:list:active:0"),
                InlineKeyboardButton(text="🗃️ Archived", callback_data="moodle:list:arch:0"),
            ],
            [InlineKeyboardButton(text="🔄 Force refresh", callback_data="moodle:force_refresh")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back:mygrades")],
        ]
    )


def kb_moodle_home(recent: list[dict] | None = None) -> InlineKeyboardMarkup:
    """Moodle home keyboard.

    Includes quick-access buttons for the latest detected updates.
    """
    rows = []

    rec = [x for x in (recent or []) if isinstance(x, dict)]
    for ev in rec[:3]:
        cid = int(ev.get("course_id") or 0)
        iid = str(ev.get("item_id") or "")
        if cid <= 0 or not iid:
            continue
        folder = "arch" if bool(ev.get("archived")) else "active"
        code = (ev.get("course_code") or "").strip() or "Course"
        name = (ev.get("item_name") or "").strip() or "Item"
        badge = "💬 " if ev.get("feedback_changed") else ""
        text = f"{badge}{code}: {name}"
        if len(text) > 58:
            text = text[:57] + "…"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"moodle:item:{cid}:{iid}:{folder}:all:0:0")])

    rows.append(
        [
            InlineKeyboardButton(text="📌 Active courses", callback_data="moodle:list:active:0"),
            InlineKeyboardButton(text="🗃️ Archived", callback_data="moodle:list:arch:0"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🔥 Recent updates", callback_data="moodle:recent:0")])
    rows.append([InlineKeyboardButton(text="🔄 Force refresh", callback_data="moodle:force_refresh")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="back:mygrades")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def kb_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔑 Edit creds", callback_data="settings:change_creds_confirm"),
                InlineKeyboardButton(text="🧹 Reset all", callback_data="settings:reset_confirm"),
            ],
            [InlineKeyboardButton(text="🔔 Notifications", callback_data="settings:notif")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="back:main")],
        ]
    )


def kb_settings_reset_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Yes", callback_data="reset_yes")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:settings")],
        ]
    )


def kb_settings_change_creds_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Yes", callback_data="change_creds_yes")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:settings")],
        ]
    )


def kb_notifications() -> InlineKeyboardMarkup:
    moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔔 Enable FIC ({NOTIF_DURATION_DAYS} days)", callback_data="notif:fic:on"),
                InlineKeyboardButton(text="🔕 Disable FIC", callback_data="notif:fic:off"),
            ],
            [
                InlineKeyboardButton(text=f"🔔 Enable Moodle ({moodle_days} days)", callback_data="notif:moodle:on"),
                InlineKeyboardButton(text="🔕 Disable Moodle", callback_data="notif:moodle:off"),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:settings")],
        ]
    )
