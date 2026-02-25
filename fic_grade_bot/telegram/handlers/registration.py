# registration.py
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery

from .. import keyboards
from ...db import database as db
from ...services.grades_service import GradesService
from ...monitoring.monitoring import ensure_fic_task, cancel_task_safely, fic_monitor_tasks
from ...browser.playwright_manager import get_playwright_instance
from ...utils import safe_edit, _localize_known_error, format_dt_vancouver, short_person_name
from ...config import NOTIF_DURATION_DAYS, MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS

router = Router()


class Creds(StatesGroup):
    waiting_login = State()
    waiting_password = State()

@router.message(Creds.waiting_login, Command("start"))
@router.message(Creds.waiting_password, Command("start"))
async def cancel_creds_flow(message: Message, state: FSMContext):
    await state.clear()

    uid = message.from_user.id
    rec = await db.get_user(uid)

    if rec:
        fic_st = await db.get_fic_state(uid)
        await message.answer(
            "✅ Cancelled.\n\n"
            "🏠 <b>Main menu</b>\n"
            f"<b>FIC:</b> {'on 🔔' if rec.get('fic_active') else 'off 🔕'} | "
            f"Update: {format_dt_vancouver((fic_st or {}).get('updated_at'))}\n\n"
            "<b>Choose a section:</b>",
            reply_markup=keyboards.kb_main_menu(),
        )
    else:
        await message.answer(
            "✅ Cancelled.\n\n"
            "👋 <b>Hello!</b> I monitor your <b>FIC final grades</b> and <b>Moodle grades</b> and alert you to changes.\n\n"
            "To begin, please register (or try the demo profile).",
            reply_markup=keyboards.kb_start_new_user(),
        )


@router.callback_query(F.data == "reg:start")
async def cb_reg_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Creds.waiting_login)
    await state.update_data(mode="register")
    await safe_edit(
        callback.message,
        text="🪪 Please send your <b>login</b>.\n\n(You can cancel with /start)",
        reply_markup=None,
    )


@router.message(Creds.waiting_login)
async def got_login(message: Message, state: FSMContext, bot: Bot):
    await state.update_data(login=(message.text or "").strip())
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    await bot.send_message(message.chat.id, "🔒 Now send your <b>password</b>.")
    await state.set_state(Creds.waiting_password)


@router.message(Creds.waiting_password)
async def got_password(message: Message, state: FSMContext, bot: Bot):
    uid = message.from_user.id
    data = await state.get_data()
    mode = data.get("mode", "register")
    login = (data.get("login") or "").strip()
    password = (message.text or "").strip()

    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    progress_msg = await bot.send_message(message.chat.id, "⏳ <b>Signing in…</b>")

    shared_pw = await get_playwright_instance()
    svc = GradesService(shared_pw=shared_pw)

    display_name: str | None = None

    try:
        # Validate credentials against FIC (and try to extract the student's name)
        await svc.fic.login(login, password)
        try:
            display_name = await svc.fic.fetch_profile_name()
        except Exception:
            display_name = None
        await svc.fic.logout()
    except Exception as e:
        err = _localize_known_error(str(e))
        await svc.close()
        await progress_msg.edit_text(f"❌ <b>Sign-in error:</b> {err or 'unknown error'}")
        await bot.send_message(
            message.chat.id,
            "Please try again: send your <b>login</b> then your <b>password</b>. Or /start to cancel.",
        )
        await state.set_state(Creds.waiting_login)
        return
    finally:
        await svc.close()

    await progress_msg.edit_text("✅ OK. Saving…")
    await db.save_credentials(uid, login, password)

    # Save display name (if we could extract it)
    if display_name:
        try:
            await db.set_display_name(uid, display_name)
        except Exception:
            pass
    await state.clear()

    rec = await db.get_user(uid)
    short_name = short_person_name((rec or {}).get("display_name"))
    # Name should only appear in the sign-in/registration confirmation message.
    greet = f"👋 <b>Hi, {short_name}!</b>\n\n" if short_name else ""
    if mode == "register":
        if rec and rec.get("fic_active"):
            ensure_fic_task(bot, uid)
        moodle_days = min(MOODLE_NOTIF_DURATION_DAYS, MOODLE_NOTIF_MAX_DAYS)
        await bot.send_message(
            message.chat.id,
            greet +
            "✅ <b>Thanks for registering!</b> Notifications are ON for FIC and Moodle.\n\n"
            f"ℹ️ FIC: <b>{NOTIF_DURATION_DAYS} days</b> (auto-off). Moodle: <b>{moodle_days} days</b> (auto-off).",
        )
    else:  # change
        if rec and rec.get("fic_active"):
            await cancel_task_safely(fic_monitor_tasks.get(uid))
            ensure_fic_task(bot, uid)
        # Still a sign-in flow, so it's okay to greet here.
        await bot.send_message(message.chat.id, greet + "🔐 <b>Credentials updated.</b>")

    fic_st = await db.get_fic_state(uid)
    await bot.send_message(
        message.chat.id,
        (
            "🏠 <b>Main menu</b>\n"
            + f"<b>FIC:</b> {'on 🔔' if rec and rec.get('fic_active') else 'off 🔕'} | "
            + f"Update: {format_dt_vancouver(fic_st.get('updated_at'))}\n\n"
            + "<b>Choose a section:</b>"
        ),
        reply_markup=keyboards.kb_main_menu(),
    )
