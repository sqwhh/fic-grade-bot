# common.py
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from .. import keyboards
from ...db import database as db
from ...monitoring.monitoring import ensure_fic_task, cancel_task_safely, fic_monitor_tasks
from .demo import cancel_demo_tasks
from ...utils import format_dt_vancouver, safe_edit, _short_err, _localize_known_error

router = Router()


async def _notifications_line(uid: int) -> str:
    rec = await db.get_user(uid)
    fic_st = await db.get_fic_state(uid)
    moodle_st = await db.get_moodle_state(uid)
    return (
        f"<b>FIC:</b> {'on 🔔' if rec and rec.get('fic_active') else 'off 🔕'} | "
        f"Update: {format_dt_vancouver((fic_st or {}).get('updated_at'))}\n"
        f"<b>Moodle:</b> {'on 🔔' if rec and rec.get('moodle_active') else 'off 🔕'} | "
        f"Update: {format_dt_vancouver((moodle_st or {}).get('updated_at'))}\n"
    )


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    rec = await db.get_user(uid)
    if rec:
        text = await _notifications_line(uid)
        await message.answer(
            "🏠 <b>Main menu</b>\n" + text + "\n<b>Choose a section:</b>",
            reply_markup=keyboards.kb_main_menu(),
        )
    else:
        await message.answer(
            "👋 <b>Hello!</b> I monitor your <b>FIC final grades</b> and <b>Moodle grades</b> and alert you to changes.\n\n"
            "To begin, please register (or try the demo profile).",
            reply_markup=keyboards.kb_start_new_user(),
        )


@router.callback_query(F.data == "back:main")
async def cb_back_main(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    text = await _notifications_line(uid)
    await safe_edit(
        callback.message,
        text=("🏠 <b>Main menu</b>\n" + text + "\n<b>Choose a section:</b>"),
        reply_markup=keyboards.kb_main_menu(),
    )


@router.callback_query(F.data == "menu:mygrades")
async def cb_menu_mygrades(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id
    fic_st = await db.get_fic_state(uid)
    moodle_st = await db.get_moodle_state(uid)
    text = (
        "📚 <b>My Grades</b>\n\n"
        f"📗 FIC updated: {format_dt_vancouver((fic_st or {}).get('updated_at'))}\n"
        f"📙 Moodle updated: {format_dt_vancouver((moodle_st or {}).get('updated_at'))}"
    )
    await safe_edit(callback.message, text=text, reply_markup=keyboards.kb_my_grades_menu())


@router.message(Command("mygrades"))
async def cmd_mygrades(message: Message):
    """Open the My Grades menu (FIC + Moodle)."""
    uid = message.from_user.id
    if not await db.get_user(uid):
        await message.answer("Please /start and register first.")
        return

    fic_st = await db.get_fic_state(uid)
    moodle_st = await db.get_moodle_state(uid)
    text = (
        "📚 <b>My Grades</b>\n\n"
        f"📗 FIC updated: {format_dt_vancouver((fic_st or {}).get('updated_at'))}\n"
        f"📙 Moodle updated: {format_dt_vancouver((moodle_st or {}).get('updated_at'))}"
    )
    await message.answer(text, reply_markup=keyboards.kb_my_grades_menu())


@router.message(Command("status"))
async def cmd_status(message: Message):
    uid = message.from_user.id
    rec = await db.get_user(uid)
    if not rec:
        await message.answer("Please /start and register first.")
        return

    fic_st = await db.get_fic_state(uid)
    moodle_st = await db.get_moodle_state(uid)
    lines = []
    if fic_st.get("last_error"):
        lines.append(f"⚠️ <b>FIC problem:</b> {_short_err(_localize_known_error(fic_st['last_error']))}")

    if moodle_st.get("last_error"):
        lines.append(f"⚠️ <b>Moodle problem:</b> {_short_err(_localize_known_error(moodle_st['last_error']))}")

    lines.append((await _notifications_line(uid)).rstrip())
    await message.answer("\n".join(lines))


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    uid = message.from_user.id
    await cancel_demo_tasks(uid)
    await cancel_task_safely(fic_monitor_tasks.get(uid))
    await db.set_fic_active(uid, False)
    await db.set_moodle_active(uid, False)
    await message.answer("🔕 Notifications are OFF (FIC + Moodle).")


@router.message(Command("start_monitor"))
async def cmd_start_monitor(message: Message, bot: Bot):
    uid = message.from_user.id
    if not await db.get_user(uid):
        await message.answer("Please /start and register first.")
        return
    await db.set_fic_active(uid, True)
    ensure_fic_task(bot, uid)
    await message.answer("✅ Notifications are ON (FIC).\n\nTip: You can also enable Moodle monitoring in Settings → Notifications.")


@router.message(F.text)
async def fallback(message: Message):
    await message.answer("Available commands: /start, /mygrades, /moodle, /status, /stop, /start_monitor, /delete")
