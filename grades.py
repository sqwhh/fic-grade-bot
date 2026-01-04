# grades.py
from typing import Dict

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

import keyboards
import database as db
import messages
from config import fernet
from grades_service import GradesService
from playwright_manager import get_playwright_instance
from utils import safe_edit, normalize_snapshot, compute_hash, _short_err, _localize_known_error

router = Router()

# Per-user view state: "grades" or "gpa"
VIEW_STATE: Dict[int, str] = {}


async def get_cached_fic_grades_map(user_id: int) -> dict:
    st = await db.get_fic_state(user_id)
    return messages.parse_snapshot(st.get("last_snapshot"))


async def fetch_fic_grades_map(user_id: int) -> dict:
    rec = await db.get_user(user_id)
    if not rec:
        return {}
    login = fernet.decrypt(rec["login_enc"]).decode()
    password = fernet.decrypt(rec["password_enc"]).decode()

    shared_pw = await get_playwright_instance()
    svc = GradesService(shared_pw=shared_pw)
    try:
        grades_map = await svc.fic_final_grades(login, password)
        await db.set_fic_error(user_id, None)
        return grades_map
    finally:
        await svc.close()


@router.callback_query(F.data == "back:mygrades")
async def cb_back_mygrades(callback: CallbackQuery):
    await callback.answer()
    await safe_edit(callback.message, text="📚 <b>My Grades</b>:", reply_markup=keyboards.kb_my_grades_menu())


@router.message(Command("mygrades"))
@router.callback_query(F.data == "menu:fic_grades")
async def show_fic_grades(event: Message | CallbackQuery):
    uid = event.from_user.id
    if isinstance(event, CallbackQuery):
        await event.answer()

    cached = await get_cached_fic_grades_map(uid)
    text = messages.build_fic_grades_view(cached)
    VIEW_STATE[uid] = "grades"

    if isinstance(event, Message):
        await event.answer(text, reply_markup=keyboards.kb_fic_grades_menu())
    else:
        await safe_edit(event.message, text=text, reply_markup=keyboards.kb_fic_grades_menu())


@router.callback_query(F.data == "grades:gpa_cached")
async def cb_grades_gpa_cached(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id

    cached = await get_cached_fic_grades_map(uid)
    already = VIEW_STATE.get(uid) == "gpa"
    footer = "ℹ️ GPA already calculated." if already else None

    text = messages.build_fic_gpa_view(cached, footer=footer)
    VIEW_STATE[uid] = "gpa"
    await safe_edit(callback.message, text=text, reply_markup=keyboards.kb_fic_grades_menu())


@router.callback_query(F.data == "grades:force_refresh")
async def cb_grades_force_refresh(callback: CallbackQuery):
    await callback.answer("In progress...")
    uid = callback.from_user.id

    cached = await get_cached_fic_grades_map(uid)
    current_view_builder = messages.build_fic_gpa_view if VIEW_STATE.get(uid) in {"gpa", "force_refresh_gpa"} else messages.build_fic_grades_view

    pre_text = current_view_builder(cached, footer="⏳ Updating… (~4 sec)")
    await safe_edit(callback.message, text=pre_text, reply_markup=keyboards.kb_fic_grades_menu())

    try:
        grades_map = await fetch_fic_grades_map(uid)
        snap = normalize_snapshot(grades_map)
        h = compute_hash(snap)
        await db.update_fic_snapshot(uid, snap, h)

        already = VIEW_STATE.get(uid) in {"force_refresh", "force_refresh_gpa"}
        footer = "✅ Updated again" if already else "✅ Updated"
        final_text = current_view_builder(grades_map, footer=footer)

        VIEW_STATE[uid] = "force_refresh_gpa" if VIEW_STATE.get(uid) in {"gpa", "force_refresh_gpa"} else "force_refresh"
        await safe_edit(callback.message, text=final_text, reply_markup=keyboards.kb_fic_grades_menu())

    except Exception as e:
        err_text = f"⚠️ <b>Error:</b> {_short_err(_localize_known_error(str(e)))}"
        error_view = current_view_builder(cached, footer=err_text)
        await safe_edit(callback.message, text=error_view, reply_markup=keyboards.kb_fic_grades_menu())
