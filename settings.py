# settings.py
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import keyboards
import database as db
from monitoring import fic_monitor_tasks, ensure_fic_task, cancel_task_safely
from registration import Creds
from utils import safe_edit, format_dt_vancouver
from config import NOTIF_DURATION_DAYS

router = Router()


async def build_notifications_panel(uid: int) -> str:
    # Older DBs may not have an expiry timestamp yet; set it lazily so UI is accurate.
    await db.ensure_fic_until_set(uid)
    rec = await db.get_user(uid)
    fic_st = await db.get_fic_state(uid)
    fic_on = bool(rec and rec.get("fic_active"))
    left = db.fic_notif_days_left(rec) if fic_on else None
    tail = f" (auto-off in {left} day{'s' if left != 1 else ''})" if fic_on and left is not None else ""
    return (
        f"<b>FIC:</b> {'on 🔔' if fic_on else 'off 🔕'}{tail} | "
        f"Update: {format_dt_vancouver((fic_st or {}).get('updated_at'))}\n"
    )


async def _render_settings(callback: CallbackQuery) -> None:
    uid = callback.from_user.id
    head = "⚙️ <b>Settings</b>\n\n"
    text = await build_notifications_panel(uid)
    note = f"\nℹ️ Notifications can be enabled for <b>{NOTIF_DURATION_DAYS} days</b> only, then they turn off automatically."
    await safe_edit(callback.message, text=head + text + note, reply_markup=keyboards.kb_settings_menu())


@router.callback_query(F.data.in_({"menu:settings", "back:settings"}))
async def menu_settings(callback: CallbackQuery):
    await callback.answer()
    await _render_settings(callback)


@router.callback_query(F.data == "settings:change_creds_confirm")
async def cb_settings_change_creds_confirm(callback: CallbackQuery):
    await callback.answer()
    await safe_edit(
        callback.message,
        text="🔑 <b>Change login/password?</b>",
        reply_markup=keyboards.kb_settings_change_creds_confirm(),
    )


@router.callback_query(F.data == "change_creds_yes")
async def cb_change_creds_yes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Creds.waiting_login)
    await state.update_data(mode="change")
    await safe_edit(
        callback.message,
        text="🪪 Please send your <b>login</b>.\n\n(You can cancel with /start)",
        reply_markup=None,
    )


@router.callback_query(F.data == "settings:reset_confirm")
async def cb_settings_reset_confirm(callback: CallbackQuery):
    await callback.answer()
    await safe_edit(
        callback.message,
        text="🧹 <b>Reset all settings and data?</b>",
        reply_markup=keyboards.kb_settings_reset_confirm(),
    )


@router.callback_query(F.data == "reset_yes")
async def cb_reset_yes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    uid = callback.from_user.id

    await cancel_task_safely(fic_monitor_tasks.get(uid))
    await db.delete_user_data(uid)
    await state.clear()

    await safe_edit(callback.message, text="✅ <b>Done.</b> Settings have been reset.", reply_markup=None)
    await callback.message.answer(
        "👋 <b>Hello!</b> To use the bot again, please register.",
        reply_markup=keyboards.kb_start_new_user(),
    )


@router.callback_query(F.data == "settings:notif")
async def cb_settings_notif(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    text = await build_notifications_panel(uid)
    note = f"\nℹ️ Notifications stay enabled for <b>{NOTIF_DURATION_DAYS} days</b> and then turn off automatically."
    header = "🔔 <b>Grade notifications</b>\n\n" + text + note
    await safe_edit(callback.message, text=header, reply_markup=keyboards.kb_notifications())


async def _refresh_notif_panel(callback: CallbackQuery) -> None:
    uid = callback.from_user.id
    text = await build_notifications_panel(uid)
    note = f"\nℹ️ Notifications stay enabled for <b>{NOTIF_DURATION_DAYS} days</b> and then turn off automatically."
    header = "🔔 <b>Grade notifications</b>\n\n"
    await safe_edit(callback.message, text=header + text + note, reply_markup=keyboards.kb_notifications())


@router.callback_query(F.data == "notif:fic:on")
async def cb_notif_fic_on(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    uid = callback.from_user.id
    await db.set_fic_active(uid, True)
    ensure_fic_task(bot, uid)
    await _refresh_notif_panel(callback)


@router.callback_query(F.data == "notif:fic:off")
async def cb_notif_fic_off(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    await db.set_fic_active(uid, False)
    await cancel_task_safely(fic_monitor_tasks.get(uid))
    await _refresh_notif_panel(callback)


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    uid = message.from_user.id
    await cancel_task_safely(fic_monitor_tasks.get(uid))
    await db.delete_user_data(uid)
    await message.answer("🗑️ <b>Data deleted, notifications off.</b> Use /start to register again.")
