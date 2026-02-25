# grades.py
import re
from datetime import datetime, timezone
from typing import Dict

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from .. import keyboards
from ...db import database as db
from .. import messages
from ...config import fernet
from ...services.grades_service import GradesService
from ...browser.playwright_manager import get_playwright_instance
from ...utils import safe_edit, normalize_snapshot, compute_hash, _short_err, _localize_known_error, format_dt_vancouver

router = Router()

# Per-user view state: "grades" or "gpa"
VIEW_STATE: Dict[int, str] = {}


async def get_cached_fic_grades_map(user_id: int) -> dict:
    st = await db.get_fic_state(user_id)
    return messages.parse_snapshot(st.get("last_snapshot"))


async def get_cached_moodle_snapshot(user_id: int) -> dict:
    st = await db.get_moodle_state(user_id)
    return messages.parse_snapshot(st.get("last_snapshot"))


async def fetch_fic_grades_map(user_id: int) -> dict:
    rec = await db.get_user(user_id)
    if not rec:
        return {}

    # Demo profile: never call real portals.
    if bool(rec.get("is_demo")):
        st = await db.get_fic_state(user_id)
        return messages.parse_snapshot(st.get("last_snapshot"))

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


async def fetch_moodle_snapshot(user_id: int) -> dict:
    rec = await db.get_user(user_id)
    if not rec:
        return {}

    # Demo profile: never call real portals.
    if bool(rec.get("is_demo")):
        st = await db.get_moodle_state(user_id)
        return messages.parse_snapshot(st.get("last_snapshot"))

    login = fernet.decrypt(rec["login_enc"]).decode()
    password = fernet.decrypt(rec["password_enc"]).decode()

    shared_pw = await get_playwright_instance()
    svc = GradesService(shared_pw=shared_pw)
    try:
        snapshot = await svc.moodle_full_snapshot(login, password)
        await db.set_moodle_error(user_id, None)
        return snapshot
    finally:
        await svc.close()


@router.callback_query(F.data == "back:mygrades")
async def cb_back_mygrades(callback: CallbackQuery):
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


@router.callback_query(F.data == "menu:fic_grades")
async def show_fic_grades(event: Message | CallbackQuery):
    uid = event.from_user.id
    if isinstance(event, CallbackQuery):
        await event.answer()

    cached = await get_cached_fic_grades_map(uid)
    st = await db.get_fic_state(uid)
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    text = messages.build_fic_grades_view(cached, extra_line=extra)
    VIEW_STATE[uid] = "grades"

    if isinstance(event, Message):
        await event.answer(text, reply_markup=keyboards.kb_fic_grades_menu())
    else:
        await safe_edit(event.message, text=text, reply_markup=keyboards.kb_fic_grades_menu())


@router.callback_query(F.data == "menu:moodle_grades")
async def show_moodle_grades(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id

    cached = await get_cached_moodle_snapshot(uid)
    st = await db.get_moodle_state(uid)
    recent = messages.parse_snapshot((st or {}).get("last_changes")) if (st or {}).get("last_changes") else []
    if not isinstance(recent, list):
        recent = []
    if not isinstance(recent, list):
        recent = []
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    text = messages.build_moodle_home_view(cached, extra_line=extra, recent=recent)
    await safe_edit(callback.message, text=text, reply_markup=keyboards.kb_moodle_home(recent))


@router.message(Command("moodle"))
async def cmd_moodle_grades(message: Message):
    """Shortcut command to open Moodle grades."""
    uid = message.from_user.id
    cached = await get_cached_moodle_snapshot(uid)
    st = await db.get_moodle_state(uid)
    recent = messages.parse_snapshot((st or {}).get("last_changes")) if (st or {}).get("last_changes") else []
    if not isinstance(recent, list):
        recent = []
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    text = messages.build_moodle_home_view(cached, extra_line=extra, recent=recent)
    await message.answer(text, reply_markup=keyboards.kb_moodle_home(recent))


@router.callback_query(F.data == "grades:gpa_cached")
async def cb_grades_gpa_cached(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id

    cached = await get_cached_fic_grades_map(uid)
    st = await db.get_fic_state(uid)
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    already = VIEW_STATE.get(uid) == "gpa"
    footer = "ℹ️ GPA already calculated." if already else None

    text = messages.build_fic_gpa_view(cached, footer=footer, extra_line=extra)
    VIEW_STATE[uid] = "gpa"
    await safe_edit(callback.message, text=text, reply_markup=keyboards.kb_fic_grades_menu())


@router.callback_query(F.data == "grades:force_refresh")
async def cb_grades_force_refresh(callback: CallbackQuery):
    await callback.answer("In progress...")
    uid = callback.from_user.id

    cached = await get_cached_fic_grades_map(uid)
    st = await db.get_fic_state(uid)
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    current_view_builder = messages.build_fic_gpa_view if VIEW_STATE.get(uid) in {"gpa", "force_refresh_gpa"} else messages.build_fic_grades_view

    pre_text = current_view_builder(cached, footer="⏳ Updating… (~4 sec)", extra_line=extra)
    await safe_edit(callback.message, text=pre_text, reply_markup=keyboards.kb_fic_grades_menu())

    try:
        grades_map = await fetch_fic_grades_map(uid)
        snap = normalize_snapshot(grades_map)
        h = compute_hash(snap)
        await db.update_fic_snapshot(uid, snap, h)

        already = VIEW_STATE.get(uid) in {"force_refresh", "force_refresh_gpa"}
        footer = "✅ Updated again" if already else "✅ Updated"
        # refresh state for updated timestamp
        st2 = await db.get_fic_state(uid)
        extra2 = f"🕒 Updated: {format_dt_vancouver((st2 or {}).get('updated_at'))}"
        final_text = current_view_builder(grades_map, footer=footer, extra_line=extra2)

        VIEW_STATE[uid] = "force_refresh_gpa" if VIEW_STATE.get(uid) in {"gpa", "force_refresh_gpa"} else "force_refresh"
        await safe_edit(callback.message, text=final_text, reply_markup=keyboards.kb_fic_grades_menu())

    except Exception as e:
        err_text = f"⚠️ <b>Error:</b> {_short_err(_localize_known_error(str(e)))}"
        error_view = current_view_builder(cached, footer=err_text, extra_line=extra)
        await safe_edit(callback.message, text=error_view, reply_markup=keyboards.kb_fic_grades_menu())


@router.callback_query(F.data == "moodle:force_refresh")
async def cb_moodle_force_refresh(callback: CallbackQuery):
    await callback.answer("In progress...")
    uid = callback.from_user.id

    cached = await get_cached_moodle_snapshot(uid)
    st = await db.get_moodle_state(uid)
    recent0 = messages.parse_snapshot((st or {}).get("last_changes")) if (st or {}).get("last_changes") else []
    if not isinstance(recent0, list):
        recent0 = []
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    pre_text = messages.build_moodle_home_view(cached, footer="⏳ Updating… (~4 sec)", extra_line=extra)
    await safe_edit(callback.message, text=pre_text, reply_markup=keyboards.kb_moodle_home(recent0))

    try:
        snapshot = await fetch_moodle_snapshot(uid)
        snap = normalize_snapshot(snapshot)
        h = compute_hash(snap)

        # Record recent changes for quick access UI.
        last_hash = (st or {}).get("last_hash")
        events = None
        if last_hash and last_hash != h:
            changes = messages.find_new_or_changed_moodle_items((st or {}).get("last_snapshot"), snapshot)
            now_iso = datetime.now(timezone.utc).isoformat()
            events = messages.compress_moodle_changes_for_recent(changes, now_iso=now_iso)

        await db.update_moodle_snapshot(uid, snap, h, recent_events=(events if events is not None else None))
        st2 = await db.get_moodle_state(uid)
        extra2 = f"🕒 Updated: {format_dt_vancouver((st2 or {}).get('updated_at'))}"

        # Use stored recent events in the home view.
        st2 = await db.get_moodle_state(uid)
        recent = messages.parse_snapshot((st2 or {}).get("last_changes")) if (st2 or {}).get("last_changes") else []
        if not isinstance(recent, list):
            recent = []
        final_text = messages.build_moodle_home_view(snapshot, footer="✅ Updated", extra_line=extra2, recent=recent)
        await safe_edit(callback.message, text=final_text, reply_markup=keyboards.kb_moodle_home(recent))

    except Exception as e:
        err_text = f"⚠️ <b>Error:</b> {_short_err(_localize_known_error(str(e)))}"
        error_view = messages.build_moodle_home_view(cached, footer=err_text, extra_line=extra, recent=recent0)
        await safe_edit(callback.message, text=error_view, reply_markup=keyboards.kb_moodle_home(recent0))


# -----------------------
# Moodle detailed browsing
# -----------------------

def _kb_moodle_course_list(snapshot: dict, *, archived: bool, page: int, page_size: int = 8) -> InlineKeyboardMarkup:
    courses = (snapshot or {}).get("courses") if isinstance((snapshot or {}).get("courses"), list) else []
    courses = [c for c in courses if bool((c or {}).get("archived")) == archived]

    # Newest term first, coded courses first.
    def term_num(lbl: str) -> int:
        s = (lbl or "").strip().upper()
        m = re.search(r"\b(\d{6})\b", s)
        return int(m.group(1)) if m else 0

    def key(c: dict):
        t = term_num(str(c.get("term_label") or ""))
        code = str(c.get("course_code") or "").strip()
        has_code = 1 if code else 0
        name = str(c.get("name") or "")
        return (-t, -has_code, code.upper(), name.upper())

    courses.sort(key=key)

    total = len(courses)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(int(page), pages - 1))
    start = page * page_size
    end = start + page_size
    chunk = courses[start:end]

    buttons = []
    for c in chunk:
        cid = int((c.get("course_id") or 0))
        code = (c.get("course_code") or "").strip() or messages._moodle_course_short_name(c.get("name") or "")
        icon = "⚠️ " if (c.get("error") or "") else ""
        # Keep button labels short so two columns look clean on mobile.
        text = f"{icon}{code}".strip()
        if len(text) > 24:
            text = text[:23] + "…"
        folder = "arch" if archived else "active"
        # tab=graded by default, items_page=0, list_page=current page
        cb = f"moodle:course:{cid}:{folder}:graded:0:{page}"
        buttons.append(InlineKeyboardButton(text=text, callback_data=cb))

    # Two courses per row for a more compact and mobile-friendly UI.
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]

    nav = []
    if pages > 1:
        prev_page = max(0, page - 1)
        next_page = min(pages - 1, page + 1)
        nav = [
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"moodle:list:{'arch' if archived else 'active'}:{prev_page}"),
            InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(text="Next ➡️", callback_data=f"moodle:list:{'arch' if archived else 'active'}:{next_page}"),
        ]

    keyboard = []
    keyboard.extend(rows)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="menu:moodle_grades")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _kb_moodle_categories(snapshot: dict, *, course_id: int, folder: str, cat_page: int, list_page: int, page_size: int = 8) -> InlineKeyboardMarkup:
    courses = (snapshot or {}).get("courses") if isinstance((snapshot or {}).get("courses"), list) else []
    c = next((x for x in courses if int((x or {}).get("course_id") or 0) == int(course_id)), None)
    items = (c or {}).get("items") if isinstance((c or {}).get("items"), list) else []

    cats = messages.moodle_list_categories(items)
    total = len(cats)
    pages = max(1, (total + page_size - 1) // page_size)
    cat_page = max(0, min(int(cat_page), pages - 1))
    start = cat_page * page_size
    end = start + page_size
    chunk = cats[start:end]

    rows = []
    for idx, cat in chunk:
        label = cat.get("label") or "(no category)"
        count = int(cat.get("count") or 0)
        fb = int(cat.get("with_feedback") or 0)
        pending = int(cat.get("pending") or 0)
        text = f"{label} ({count})"
        if fb:
            text += f" 💬{fb}"
        if pending:
            text += f" ⏳{pending}"
        if len(text) > 58:
            text = text[:57] + "…"
        cb = f"moodle:course:{course_id}:{folder}:cat{idx}:0:{list_page}"
        rows.append([InlineKeyboardButton(text=text, callback_data=cb)])

    nav = []
    if pages > 1:
        prev_page = max(0, cat_page - 1)
        next_page = min(pages - 1, cat_page + 1)
        nav = [
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"moodle:course:{course_id}:{folder}:cats:{prev_page}:{list_page}"),
            InlineKeyboardButton(text=f"{cat_page+1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(text="Next ➡️", callback_data=f"moodle:course:{course_id}:{folder}:cats:{next_page}:{list_page}"),
        ]

    keyboard = []
    keyboard.extend(rows)
    if nav:
        keyboard.append(nav)
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"moodle:course:{course_id}:{folder}:graded:0:{list_page}"),
        InlineKeyboardButton(text="⬅️ Courses", callback_data=f"moodle:list:{folder}:{list_page}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _kb_moodle_course_items(
    snapshot: dict,
    *,
    course_id: int,
    folder: str,
    tab: str,
    items_page: int,
    list_page: int,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    courses = (snapshot or {}).get("courses") if isinstance((snapshot or {}).get("courses"), list) else []
    c = next((x for x in courses if int((x or {}).get("course_id") or 0) == int(course_id)), None)
    items = (c or {}).get("items") if isinstance((c or {}).get("items"), list) else []

    filtered = messages.moodle_filter_items(items, tab=tab)

    total = len(filtered)
    pages = max(1, (total + page_size - 1) // page_size)
    items_page = max(0, min(int(items_page), pages - 1))
    start = items_page * page_size
    end = start + page_size
    chunk = filtered[start:end]

    rows = []
    for it in chunk:
        iid = str((it or {}).get("item_id") or "")
        name = messages.moodle_clean_item_name((it.get("name") or "").strip())
        val = messages.moodle_item_compact_value(it)
        icon = messages.moodle_item_icon(it)
        text = f"{icon} {name} — {val}".strip()
        if len(text) > 58:
            text = text[:57] + "…"
        cb = f"moodle:item:{course_id}:{iid}:{folder}:{tab}:{items_page}:{list_page}"
        rows.append([InlineKeyboardButton(text=text, callback_data=cb)])

    nav = []
    if pages > 1:
        prev_page = max(0, items_page - 1)
        next_page = min(pages - 1, items_page + 1)
        nav = [
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"moodle:course:{course_id}:{folder}:{tab}:{prev_page}:{list_page}"),
            InlineKeyboardButton(text=f"{items_page+1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(text="Next ➡️", callback_data=f"moodle:course:{course_id}:{folder}:{tab}:{next_page}:{list_page}"),
        ]

    keyboard = [
        [
            InlineKeyboardButton(text="✅ Graded", callback_data=f"moodle:course:{course_id}:{folder}:graded:0:{list_page}"),
            InlineKeyboardButton(text="💬 Feedback", callback_data=f"moodle:course:{course_id}:{folder}:feedback:0:{list_page}"),
            InlineKeyboardButton(text="⏳ Pending", callback_data=f"moodle:course:{course_id}:{folder}:pending:0:{list_page}"),
        ],
        [
            InlineKeyboardButton(text="🧮 Totals", callback_data=f"moodle:course:{course_id}:{folder}:totals:0:{list_page}"),
            InlineKeyboardButton(text="🧩 Non-graded", callback_data=f"moodle:course:{course_id}:{folder}:nongraded:0:{list_page}"),
            InlineKeyboardButton(text="📋 All", callback_data=f"moodle:course:{course_id}:{folder}:all:0:{list_page}"),
        ],
    ]
    keyboard.extend(rows)
    if nav:
        keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton(text="📂 Categories", callback_data=f"moodle:course:{course_id}:{folder}:cats:0:{list_page}"),
        InlineKeyboardButton(text="⬅️ Courses", callback_data=f"moodle:list:{folder}:{list_page}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _kb_moodle_item_detail(*, course_id: int, folder: str, tab: str, items_page: int, list_page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Back", callback_data=f"moodle:course:{course_id}:{folder}:{tab}:{items_page}:{list_page}")]
        ]
    )


def _kb_moodle_recent(recent: list[dict], *, page: int, page_size: int = 8) -> InlineKeyboardMarkup:
    """Keyboard for recent updates list."""
    rec = [x for x in (recent or []) if isinstance(x, dict)]
    total = len(rec)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(int(page), pages - 1))
    start = page * page_size
    end = start + page_size
    chunk = rec[start:end]

    rows = []
    for ev in chunk:
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
        cb = f"moodle:item:{cid}:{iid}:{folder}:all:0:0"
        rows.append([InlineKeyboardButton(text=text, callback_data=cb)])

    nav = []
    if pages > 1:
        prev_page = max(0, page - 1)
        next_page = min(pages - 1, page + 1)
        nav = [
            InlineKeyboardButton(text="⬅️ Prev", callback_data=f"moodle:recent:{prev_page}"),
            InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"),
            InlineKeyboardButton(text="Next ➡️", callback_data=f"moodle:recent:{next_page}"),
        ]

    keyboard = []
    keyboard.extend(rows)
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="⬅️ Back", callback_data="menu:moodle_grades")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.callback_query(F.data.startswith("moodle:list:"))
async def cb_moodle_list(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id

    parts = (callback.data or "").split(":")
    # moodle:list:<active|arch>:<page>
    folder = parts[2] if len(parts) > 2 else "active"
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    archived = folder == "arch"

    snapshot = await get_cached_moodle_snapshot(uid)
    st = await db.get_moodle_state(uid)
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    text = messages.build_moodle_course_list_view(snapshot, archived=archived, page=page, extra_line=extra)
    kb = _kb_moodle_course_list(snapshot, archived=archived, page=page)
    await safe_edit(callback.message, text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("moodle:recent:"))
async def cb_moodle_recent(callback: CallbackQuery):
    """Show recent Moodle changes for quick access."""
    await callback.answer()
    uid = callback.from_user.id

    parts = (callback.data or "").split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    st = await db.get_moodle_state(uid)
    recent = messages.parse_snapshot((st or {}).get("last_changes")) if (st or {}).get("last_changes") else []
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"

    text = messages.build_moodle_recent_updates_view(recent, page=page, extra_line=extra)
    kb = _kb_moodle_recent(recent, page=page)
    await safe_edit(callback.message, text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("moodle:course:"))
async def cb_moodle_course(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id

    parts = (callback.data or "").split(":")
    # moodle:course:<course_id>:<folder>:<tab>:<items_page>:<list_page>
    course_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    folder = parts[3] if len(parts) > 3 else "active"
    tab = parts[4] if len(parts) > 4 else "graded"
    items_page = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 0
    list_page = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0

    snapshot = await get_cached_moodle_snapshot(uid)
    st = await db.get_moodle_state(uid)
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"

    if tab == "cats":
        text = messages.build_moodle_categories_view(snapshot, course_id=course_id, page=items_page, extra_line=extra)
        kb = _kb_moodle_categories(snapshot, course_id=course_id, folder=folder, cat_page=items_page, list_page=list_page)
        await safe_edit(callback.message, text=text, reply_markup=kb)
        return

    text = messages.build_moodle_course_view(snapshot, course_id=course_id, tab=tab, page=items_page, extra_line=extra)
    kb = _kb_moodle_course_items(snapshot, course_id=course_id, folder=folder, tab=tab, items_page=items_page, list_page=list_page)
    await safe_edit(callback.message, text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("moodle:item:"))
async def cb_moodle_item(callback: CallbackQuery):
    await callback.answer()
    uid = callback.from_user.id

    parts = (callback.data or "").split(":")
    # moodle:item:<course_id>:<item_id>:<folder>:<tab>:<items_page>:<list_page>
    course_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    item_id = parts[3] if len(parts) > 3 else ""
    folder = parts[4] if len(parts) > 4 else "active"
    tab = parts[5] if len(parts) > 5 else "graded"
    items_page = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0
    list_page = int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else 0

    snapshot = await get_cached_moodle_snapshot(uid)
    st = await db.get_moodle_state(uid)
    extra = f"🕒 Updated: {format_dt_vancouver((st or {}).get('updated_at'))}"
    text = messages.build_moodle_item_detail_view(snapshot, course_id=course_id, item_id=item_id, extra_line=extra)
    kb = _kb_moodle_item_detail(course_id=course_id, folder=folder, tab=tab, items_page=items_page, list_page=list_page)
    await safe_edit(callback.message, text=text, reply_markup=kb)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    # Used for pagination labels
    await callback.answer()
