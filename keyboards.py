# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import NOTIF_DURATION_DAYS


def kb_start_new_user() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔐 Register", callback_data="reg:start")]]
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"🔔 Enable FIC ({NOTIF_DURATION_DAYS} days)", callback_data="notif:fic:on"),
                InlineKeyboardButton(text="🔕 Disable FIC", callback_data="notif:fic:off"),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:settings")],
        ]
    )
