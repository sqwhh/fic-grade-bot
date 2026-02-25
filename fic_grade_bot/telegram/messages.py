# messages.py
"""User-facing message builders.

Only FIC grades + GPA logic is kept.
(Moodle and Enrollment message logic was removed.)

GPA / repeat logic implemented here follows SFU's Spring 2026 calendar:
  - Only grades with a numerical equivalent are included in GPA.
  - F / FD / N count as 0.00 and do affect GPA.
  - P / W and transcript notations (AE/AU/CC/CF/CN/CR/FX/WD/WE) have
    no numerical equivalent and are excluded from GPA.
  - Temporary grades (DE/GN/IP) have no numerical equivalent and are excluded.
  - When a course is repeated, only the highest grade counts; if the same grade
    is earned, the most recent attempt is counted and earlier attempt(s) are excluded.
"""

from __future__ import annotations

import re
import html as _html
from typing import Dict, List, Optional, Tuple

from ..utils import parse_snapshot


def _h(s: str) -> str:
    """Escape user/content strings for Telegram HTML parse mode."""
    return _html.escape(s or "")


# ====== Course Credits & GPA Data ======

def get_course_credits(course_code: str) -> int:
    """Return the unit/credit value for a course code.

    Unknown courses default to 0 (won't affect GPA). If you want every course to
    count correctly, keep this mapping up to date.
    """
    courses = {
        'ALC099': 0, 'ALC101': 0, 'ARCH100': 3, 'ARCH131': 3,
        'BISC100': 4, 'BISC101': 4, 'BISC102': 4, 'BPK140': 3,
        'BUS108': 0, 'BUS200': 3, 'BUS216': 3, 'BUS251': 3,
        'CA135': 3, 'CA149': 3, 'CHEM111': 4, 'CHEM121': 4,
        'CHEM122': 2, 'CHEM126': 2, 'CMNS110': 3, 'CMNS120': 3,
        'CMNS130': 3, 'CMPT115': 3, 'CMPT120': 3, 'CMPT125': 3,
        'CMPT130': 3, 'CMPT135': 3, 'CNQS101': 0, 'CNST101': 0,
        'CNSU101': 0, 'COM001': 0, 'COM002': 0, 'CRIM101': 3,
        'CRIM131': 3, 'CRIM135': 3, 'ECN100': 0, 'ECON103': 4,
        'ECON1034': 4, 'ECON1054': 4, 'ECON105': 4, 'ECON260': 3,
        'ENF100': 0, 'ENGL112': 3, 'ENGL113': 3, 'ENGL115': 3,
        'ENSC100': 3, 'ENSC105': 3, 'ENSC180': 3, 'EVSC100': 3,
        'FREN120': 3, 'GEOG100': 3, 'GEOG104': 3, 'GSWS101': 3,
        'HIST102': 3, 'HIST204': 3, 'HSCI160': 3, 'IAT100': 3,
        'IAT102': 3, 'IAT110': 3, 'ILS101': 0, 'INDG101': 3,
        'INDG201': 3, 'INDG286': 3, 'INS101': 0, 'INS102': 0,
        'INTG100': 0, 'IS101': 3, 'IUW100': 0, 'LBST101': 3,
        'LBST201': 3, 'LING110': 3, 'LING111': 3, 'LING200': 3,
        'LING220': 3, 'MACM101': 3, 'MATH100': 3, 'MATH151': 3,
        'MATH152': 3, 'MATH157': 3, 'MATH232': 3, 'MTH099': 0,
        'MTH101': 0, 'MTH103': 0, 'PHIL105': 3, 'PHL120': 0,
        'PHYS100': 3, 'PHYS140': 4, 'PHYS1141': 1, 'PHYS141': 4,
        'POL100': 3, 'POL141': 3, 'POL151': 3, 'POL231': 3,
        'POL232': 3, 'PSYC100': 3, 'PSYC102': 3, 'PSYC109': 3,
        'PSYC201': 4, 'PSYC250': 3, 'PWR101': 0, 'REM100': 3,
        'SA150': 4, 'STAT203': 3, 'UNI101': 0, 'WIS100': 0,
        'WL101': 3, 'WL201': 3,
    }
    return courses.get(course_code, 0)


# SFU standard numeric equivalents (Spring 2026).
GRADE_POINTS: Dict[str, float] = {
    "A+": 4.33,
    "A": 4.00,
    "A-": 3.67,
    "B+": 3.33,
    "B": 3.00,
    "B-": 2.67,
    "C+": 2.33,
    "C": 2.00,
    "C-": 1.67,
    "D": 1.00,
    "F": 0.00,
    "FD": 0.00,
    "N": 0.00,
}

# Grades / notations without a numerical equivalent (excluded from GPA).
NON_GPA_GRADES = {
    # Competency / Practicum
    "P", "W",
    # Student Records and Transcript Notations
    "AE", "AU", "CC", "CF", "CN", "CR", "FX", "WD", "WE",
    # Temporary grades
    "DE", "GN", "IP",
}


def _norm_course_code(code: str) -> str:
    """Normalize course codes to a stable comparison key."""
    if not code:
        return ""
    # Keep only letters/numbers, remove spaces and punctuation.
    return re.sub(r"[^A-Z0-9]", "", code.upper().strip())


def _norm_grade(grade: str) -> str:
    """Normalize grade strings from portals.

    Examples handled:
      "A-" / "A −" (unicode minus) / "a-" -> "A-"
      "B+ (78%)" -> "B+"
      " wd " -> "WD"
    """
    if not grade:
        return ""

    g = grade.strip().upper()
    g = g.replace("−", "-")  # unicode minus

    # Keep first token before whitespace or punctuation.
    g = re.split(r"[\s(),;]+", g)[0].strip()
    return g


def grade_to_points(grade: str) -> Optional[float]:
    """Return numeric equivalent for a grade, or None if excluded from GPA."""
    g = _norm_grade(grade)
    if not g:
        return None
    if g in NON_GPA_GRADES:
        return None
    return GRADE_POINTS.get(g)


_TERM_ORDER = {
    "WINTER": 0,
    "SPRING": 1,
    "SUMMER": 2,
    "FALL": 3,
}


def _term_sort_key(term_label: str) -> tuple:
    """Best-effort chronological sort for term labels.

    Supports labels like:
      - "Spring 2026"
      - "2026 Spring"
      - "FALL 2025 (FIC)"
    """
    s = (term_label or "").upper()

    # Find a year anywhere in the label.
    m = re.search(r"(19|20)\d{2}", s)
    year = int(m.group(0)) if m else 0

    term_rank = 99
    for name, rank in _TERM_ORDER.items():
        if name in s:
            term_rank = rank
            break

    # Fallback: sort unknown labels last but deterministically.
    return (year, term_rank, s)


# ====== FIC Message Formatting ======

def format_grades_compact(grades_map: Dict[str, Dict[str, str]]) -> str:
    if not grades_map:
        return "No saved grades yet. Press “Force refresh” to fetch."

    lines: List[str] = []
    sems = sorted(grades_map.keys(), key=_term_sort_key)
    for i, sem in enumerate(sems):
        lines.append(f"🗓 <b>{sem}</b>")
        inner = grades_map.get(sem) or {}
        for code, grade in sorted(inner.items()):
            g = (grade or "").strip() or "—"
            lines.append(f"  • {code}: {g}")
        if i < len(sems) - 1:
            lines.append("")
    return "\n".join(lines)


def format_gpa_report_compact(grades_map: Dict[str, Dict[str, str]]) -> str:
    """Compute GPA using SFU numeric equivalents and repeat exclusion."""
    if not grades_map:
        return "No graded courses yet."

    lines: List[str] = [
        "<b>📊 GPA Calculation</b>",
        "Legend: ",
        " • 🚫 excluded (repeat) ",
        " • ⏭ not in GPA",
    ]

    sems = sorted(grades_map.keys(), key=_term_sort_key)

    # ---- Flatten attempts in chronological order ----
    # attempt_key provides a stable “most recent” ordering.
    attempts: List[dict] = []
    for sem_index, sem in enumerate(sems):
        inner = grades_map.get(sem) or {}
        # stable ordering inside term
        for pos, (code_raw, grade_raw) in enumerate(sorted(inner.items(), key=lambda x: x[0])):
            code_norm = _norm_course_code(code_raw)
            cr = get_course_credits(code_norm)
            pt = grade_to_points(grade_raw)
            attempts.append({
                "sem": sem,
                "sem_index": sem_index,
                "pos": pos,
                "attempt_key": (sem_index, pos),
                "code_raw": code_raw,
                "code_norm": code_norm,
                "grade_raw": (grade_raw or "").strip(),
                "points": pt,
                "credits": cr,
            })

    # ---- Pick the included attempt per course (highest grade; tie -> most recent) ----
    included_attempt_key_by_code: Dict[str, tuple] = {}
    best_points_by_code: Dict[str, float] = {}

    for a in attempts:
        code = a["code_norm"]
        pt = a["points"]
        if not code or pt is None:
            continue

        if code not in best_points_by_code:
            best_points_by_code[code] = pt
            included_attempt_key_by_code[code] = a["attempt_key"]
            continue

        best_pt = best_points_by_code[code]
        best_key = included_attempt_key_by_code[code]
        if (pt > best_pt) or (pt == best_pt and a["attempt_key"] > best_key):
            best_points_by_code[code] = pt
            included_attempt_key_by_code[code] = a["attempt_key"]

    # ---- Compute term GPA (after repeat exclusions) and cumulative GPA ----
    total_points = 0.0
    total_credits = 0

    for sem in sems:
        sem_points = 0.0
        sem_credits = 0

        lines.append(f"\n🗓 <b>{sem}</b>")

        term_attempts = [a for a in attempts if a["sem"] == sem]
        term_attempts.sort(key=lambda x: x["code_norm"])  # show in code order

        for a in term_attempts:
            code_disp = a["code_raw"]
            grade_disp = a["grade_raw"] or "—"
            cr = a["credits"]
            pt = a["points"]

            # No grade / not in GPA (no numeric equivalent)
            if pt is None:
                lines.append(f"  • {code_disp} ({cr} cr): {grade_disp} ⏭")
                continue

            # Defensive: unknown grade token -> not in GPA
            if _norm_grade(grade_disp) not in GRADE_POINTS:
                lines.append(f"  • {code_disp} ({cr} cr): {grade_disp} ⏭")
                continue

            # 0-credit courses do not affect GPA.
            if cr <= 0:
                lines.append(f"  • {code_disp} ({cr} cr): {grade_disp} ⏭")
                continue

            included = included_attempt_key_by_code.get(a["code_norm"]) == a["attempt_key"]
            tag = "" if included else "🚫"
            lines.append(f"  • {code_disp} ({cr} cr): {grade_disp} {tag}")

            if included:
                sem_points += pt * cr
                sem_credits += cr
                total_points += pt * cr
                total_credits += cr

        sem_gpa = (sem_points / sem_credits) if sem_credits > 0 else 0.0
        lines.append(f"  ➤ Counted credits: {sem_credits} | GPA: {sem_gpa:.2f}")

    cum_gpa = (total_points / total_credits) if total_credits > 0 else 0.0
    lines.append(f"\n🔢 Total counted credits: <b>{total_credits}</b>")
    lines.append(f"🏁 Cumulative GPA: <b>{cum_gpa:.2f}</b>")

    return "\n".join(lines)


# ====== Message View Builders ======

def fic_header(extra_line: str | None = None) -> str:
    base = "<b>📗 FIC grades</b>\n"
    if extra_line:
        base += f"{extra_line}\n"
    return base


def moodle_header(extra_line: str | None = None) -> str:
    base = "<b>📙 Moodle grades</b>\n"
    if extra_line:
        base += f"{extra_line}\n"
    return base


def build_fic_grades_view(grades_map: dict, footer: str | None = None, *, extra_line: str | None = None) -> str:
    body = format_grades_compact(grades_map or {})
    parts = [fic_header(extra_line), body]
    if footer:
        parts.append(f"\n{footer}")
    return "\n".join(parts)


def build_fic_gpa_view(grades_map: dict, footer: str | None = None, *, extra_line: str | None = None) -> str:
    body = format_gpa_report_compact(grades_map or {})
    parts = [fic_header(extra_line), body]
    if footer:
        parts.append(f"\n{footer}")
    return "\n".join(parts)


def _moodle_term_sort_key(term_label: str) -> tuple:
    """Sort keys like 'FIC 202503' chronologically (best-effort)."""
    s = (term_label or "").upper().strip()
    m = re.search(r"\bFIC\s+(\d{6})\b", s)
    if m:
        return (int(m.group(1)), s)
    return _term_sort_key(term_label)


def format_moodle_grades_compact(grades_map: Dict[str, Dict[str, str]]) -> str:
    if not grades_map:
        return "No saved Moodle grades yet. Press “Force refresh” to fetch."

    lines: List[str] = []
    sems = sorted(grades_map.keys(), key=_moodle_term_sort_key)
    for i, sem in enumerate(sems):
        lines.append(f"🗓 <b>{sem}</b>")
        inner = grades_map.get(sem) or {}
        for code, grade in sorted(inner.items()):
            g = (grade or "").strip() or "—"
            lines.append(f"  • {code}: {g}")
        if i < len(sems) - 1:
            lines.append("")
    return "\n".join(lines)


def build_moodle_grades_view(grades_map: dict, footer: str | None = None, *, extra_line: str | None = None) -> str:
    body = format_moodle_grades_compact(grades_map or {})
    parts = [moodle_header(extra_line), body]
    if footer:
        parts.append(f"\n{footer}")
    return "\n".join(parts)




# ====== Moodle Detailed Views (Courses + Items) ======

def _moodle_snapshot_courses(snapshot: dict) -> List[dict]:
    courses = (snapshot or {}).get("courses")
    raw = courses if isinstance(courses, list) else []
    # Defensive filtering: older snapshots might contain malformed rows (empty name/url).
    out: List[dict] = []
    seen: set[int] = set()
    for c in raw:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        url = (c.get("url") or "").strip()
        try:
            cid = int(c.get("course_id") or 0)
        except Exception:
            cid = 0
        if not name or not url or cid <= 0:
            continue
        if "course/user.php" not in url:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(c)
    return out


def _moodle_course_short_name(full_name: str) -> str:
    """Make a compact human-friendly course title for Telegram."""
    s = (full_name or "").strip()
    s = re.sub(r"\s+", " ", s)
    # Remove leading term + token like "FIC 202503 CMPT135_YEJI"
    s = re.sub(r"^FIC\s+\d{6}\s+[^\s]+\s*", "", s, flags=re.I)
    # Remove trailing "(archived)" markers
    s = re.sub(r"\(archived\)", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s or (full_name or "").strip()


def moodle_clean_item_name(name: str) -> str:
    """Make Moodle grade item names shorter and easier to scan in Telegram."""
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s)
    # Many items start with: "Link to Quiz activity ...".
    s = re.sub(r"^Link to\s+.*?\s+activity\s+", "", s, flags=re.I)
    return s.strip() or (name or "").strip()


def _moodle_parse_range(rng: str) -> tuple[float | None, float | None]:
    """Parse range strings like '0.00–10.00' or '0–100' into (min, max)."""
    s = (rng or "").strip().replace("−", "-")
    # En dash → hyphen for easier parsing
    s = s.replace("–", "-")
    nums = re.findall(r"-?\d+(?:\.\d+)?", s)
    if len(nums) >= 2:
        try:
            return float(nums[0]), float(nums[1])
        except Exception:
            return None, None
    return None, None


def _moodle_strip_trailing_zeros(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s


def _moodle_compact_pct(s: str) -> str:
    """Compact percentage strings like '100.00 %' -> '100%'."""
    t = (s or "").strip()
    if not t:
        return ""
    t = t.replace(" ", "")
    # Accept '100.00%' or '100.00% (A+)' etc.
    m = re.search(r"(-?\d+(?:\.\d+)?)%", t)
    if m:
        try:
            num = float(m.group(1))
            if abs(num - round(num)) < 1e-9:
                return f"{int(round(num))}%"
            # Keep one decimal for non-integers.
            return f"{num:.1f}%".rstrip("0").rstrip(".")
        except Exception:
            pass
    # If it already contains '%', return as-is.
    return t


def _moodle_compact_grade(raw: str) -> str:
    """Compact grade strings from Moodle tables."""
    s = (raw or "").strip()
    if not s:
        return ""
    s = s.replace("−", "-")

    # '(A+)' -> 'A+'
    m = re.fullmatch(r"\(([^)]+)\)", s)
    if m:
        return m.group(1).strip()

    # '100.00 % (A+)' -> '100% (A+)'
    pct = _moodle_compact_pct(s)
    letter = ""
    m2 = re.search(r"\(([A-Z][A-Z+\-]*)\)", s.upper().replace("−", "-"))
    if m2:
        letter = m2.group(1)

    if "%" in s:
        return f"{pct} ({letter})".strip() if letter else pct

    return s


def moodle_item_has_value(it: dict) -> bool:
    return bool((it.get("grade") or "").strip() or (it.get("percentage") or "").strip())


def moodle_item_has_feedback(it: dict) -> bool:
    return bool((it.get("feedback") or "").strip())


def moodle_item_is_total(it: dict) -> bool:
    name = (it.get("name") or "").strip().lower()
    if name == "course total":
        return True
    if name.endswith(" total"):
        return True
    # Weighted totals like 'Quizzes (8%)'
    if re.search(r"\(\s*\d+\s*%\s*\)", name):
        return True
    return False


def moodle_item_is_non_graded(it: dict) -> bool:
    cat = (it.get("category_path") or "").lower()
    if "non-graded" in cat or "non graded" in cat:
        return True
    mn, mx = _moodle_parse_range(it.get("range") or "")
    if mn == 0 and mx == 0:
        return True
    return False


def moodle_item_is_problem(it: dict) -> bool:
    g = (it.get("grade") or "")
    p = (it.get("percentage") or "")
    fb = (it.get("feedback") or "")
    if "(N" in g or "( N" in g or " N)" in g:
        return True
    if any(x in (fb or "").lower() for x in ("no submission", "no attempt")):
        return True
    # 0% with a non-zero range is usually "missing".
    pct = _moodle_compact_pct(p)
    mn, mx = _moodle_parse_range(it.get("range") or "")
    if pct.startswith("0") and mx and mx > 0:
        return True
    return False


def moodle_item_compact_value(it: dict) -> str:
    """Human-friendly value for lists/buttons."""
    grade_raw = (it.get("grade") or "").strip()
    pct_raw = (it.get("percentage") or "").strip()
    rng_raw = (it.get("range") or "").strip()

    grade = _moodle_compact_grade(grade_raw)
    pct = _moodle_compact_pct(pct_raw)

    # If grade already carries % info, prefer it.
    if grade and "%" in grade:
        return grade

    # Points-based items: show "x/y".
    mn, mx = _moodle_parse_range(rng_raw)
    if grade and mx and mx > 0:
        try:
            gnum = float(re.findall(r"-?\d+(?:\.\d+)?", grade)[0])
            pts = f"{_moodle_strip_trailing_zeros(gnum)}/{_moodle_strip_trailing_zeros(mx)}"
            return f"{pts} ({pct})" if pct else pts
        except Exception:
            pass

    if grade:
        return f"{grade} ({pct})" if (pct and pct not in grade) else grade
    if pct:
        return pct
    return "—"


def moodle_item_icon(it: dict) -> str:
    """Single compact icon for Moodle item status."""
    base = "✅"
    if moodle_item_is_total(it):
        base = "🧮"
    elif not moodle_item_has_value(it):
        base = "⏳"
    elif moodle_item_is_problem(it):
        base = "⚠️"
    elif moodle_item_is_non_graded(it):
        base = "🧩"

    if moodle_item_has_feedback(it):
        return f"💬{base}"
    return base


def _moodle_short_category(path: str) -> str:
    """Shorten category paths for Telegram."""
    s = (path or "").strip()
    if not s:
        return ""
    parts = [p.strip() for p in s.split(">")]
    parts = [re.sub(r"\(archived\)", "", p, flags=re.I).strip() for p in parts if p.strip()]
    # Drop generic top-level prefix if there are deeper levels.
    if len(parts) >= 2 and parts[0].lower() in {"course total"}:
        parts = parts[1:]
    # Keep last two segments.
    if len(parts) > 2:
        parts = parts[-2:]
    return " / ".join(parts)


def moodle_course_overall_grade(course: dict) -> str:
    """Prefer Overview grade, otherwise derive from the 'Course total' row."""
    g = (course.get("grade_overview") or "").strip()
    if g:
        return _moodle_compact_grade(g)
    items = course.get("items") if isinstance(course.get("items"), list) else []
    for it in items:
        if (it.get("name") or "").strip().lower() == "course total":
            val = moodle_item_compact_value(it)
            return val if val != "—" else "—"
    return "—"


def moodle_filter_items(items: list[dict], *, tab: str) -> list[dict]:
    """Filter items for a specific course tab."""
    t = (tab or "graded").strip().lower()
    # Category tab: cat<index>
    if t.startswith("cat") and t != "cats":
        try:
            idx = int(t[3:])
        except Exception:
            return []
        cats = moodle_list_categories(items)
        if idx < 0 or idx >= len(cats):
            return []
        path = cats[idx][1].get("path") or ""
        return [it for it in items if (it.get("category_path") or "").strip() == path]

    if t == "all":
        return list(items)
    if t == "feedback":
        return [it for it in items if moodle_item_has_feedback(it)]
    if t == "pending":
        return [it for it in items if (not moodle_item_has_value(it)) and (not moodle_item_is_total(it)) and (not moodle_item_has_feedback(it))]
    if t == "totals":
        return [it for it in items if moodle_item_is_total(it)]
    if t == "nongraded":
        return [it for it in items if moodle_item_is_non_graded(it)]
    # default: graded
    return [
        it
        for it in items
        if moodle_item_has_value(it)
        and (not moodle_item_is_total(it))
        and (not moodle_item_is_non_graded(it))
    ]


def moodle_list_categories(items: list[dict]) -> list[tuple[int, dict]]:
    """Return categories as a stable list of (index, info)."""
    groups: Dict[str, list[dict]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        path = (it.get("category_path") or "").strip() or "Other"
        groups.setdefault(path, []).append(it)

    keys = sorted(groups.keys(), key=lambda s: s.lower())
    out: list[tuple[int, dict]] = []
    for idx, k in enumerate(keys):
        arr = groups[k]
        out.append(
            (
                idx,
                {
                    "path": k,
                    "label": _moodle_short_category(k) or k,
                    "count": len(arr),
                    "with_feedback": sum(1 for it in arr if moodle_item_has_feedback(it)),
                    "pending": sum(1 for it in arr if (not moodle_item_has_value(it)) and (not moodle_item_has_feedback(it))),
                },
            )
        )
    return out


def build_moodle_home_view(
    snapshot: dict,
    footer: str | None = None,
    *,
    extra_line: str | None = None,
    recent: list[dict] | None = None,
) -> str:
    courses = _moodle_snapshot_courses(snapshot)
    active = sum(1 for c in courses if not bool((c or {}).get("archived")))
    archived = sum(1 for c in courses if bool((c or {}).get("archived")))

    lines: List[str] = [moodle_header(extra_line)]

    if not courses:
        lines.append("No saved Moodle grades yet. Press “Force refresh” to fetch.")
    else:
        err_count = sum(1 for c in courses if (c or {}).get("error"))
        lines.append(f"📌 Active courses: <b>{active}</b>")
        lines.append(f"🗃️ Archived courses: <b>{archived}</b>")
        if err_count:
            lines.append(f"⚠️ Courses with errors: <b>{err_count}</b>")
        # Recent updates (best effort; based on detected diffs from last snapshot).
        rec = [x for x in (recent or []) if isinstance(x, dict)]
        if rec:
            lines.append("\n🔥 <b>Recent updates</b>:")
            for ev in rec[:5]:
                code = (ev.get("course_code") or "").strip() or "(course)"
                term = (ev.get("term_label") or "").strip()
                item = (ev.get("item_name") or "").strip() or "(item)"
                val = (ev.get("new_value") or "").strip() or "—"
                badge = "💬" if ev.get("feedback_changed") else ""
                # Keep it compact.
                label = f"{badge} {code}: {item} — {val}".strip()
                if len(label) > 90:
                    label = label[:89] + "…"
                tail = f" <i>({_h(term)})</i>" if term else ""
                lines.append(f" • {_h(label)}{tail}")
            lines.append("\nTip: tap <b>Recent updates</b> to open the full list.")

        lines.append("\nTip: open a course to browse grades, feedback, totals, and categories.")

    if footer:
        lines.append(f"\n{footer}")
    return "\n".join(lines)


def build_moodle_course_list_view(snapshot: dict, *, archived: bool, page: int, page_size: int = 8, extra_line: str | None = None) -> str:
    courses = [c for c in _moodle_snapshot_courses(snapshot) if bool((c or {}).get("archived")) == archived]

    # Sort by newest term first, then prefer coded courses, then by code/name.
    def term_num(lbl: str) -> int:
        s = (lbl or "").strip().upper()
        m = re.search(r"\b(\d{6})\b", s)
        return int(m.group(1)) if m else 0

    def key(c: dict):
        t = term_num(str(c.get("term_label") or ""))
        code = str(c.get("course_code") or "").strip()
        has_code = 1 if code else 0
        name = str(c.get("name") or "")
        # Descending term + has_code.
        return (-t, -has_code, code.upper(), name.upper())

    courses.sort(key=key)

    total = len(courses)
    page = max(0, int(page))
    start = page * page_size
    end = start + page_size
    chunk = courses[start:end]
    pages = max(1, (total + page_size - 1) // page_size)

    title = "Archived courses" if archived else "Active courses"
    lines: List[str] = [moodle_header(extra_line), f"📁 <b>{title}</b> (page {page+1}/{pages})\n"]

    if not courses:
        lines.append("No courses found in this folder.")
        return "\n".join(lines)

    for c in chunk:
        code = (c.get("course_code") or "").strip()
        term = (c.get("term_label") or "").strip()
        short = _moodle_course_short_name(c.get("name") or "")
        head = f"{code}" if code else short
        grade = moodle_course_overall_grade(c)
        icon = "⚠️ " if (c.get("error") or "") else ""
        if grade and grade != "—":
            lines.append(f"• {icon}<b>{_h(head)}</b> — <b>{_h(grade)}</b>  <i>({_h(term)})</i>")
        else:
            # Avoid showing "— —" when a course has no overall grade.
            lines.append(f"• {icon}<b>{_h(head)}</b>  <i>({_h(term)})</i>")
        if short and (not code or short.lower() != code.lower()):
            lines.append(f"  {_h(short)}")

    lines.append("\nTip: tap a course below to open it.")
    return "\n".join(lines)


def build_moodle_categories_view(snapshot: dict, *, course_id: int, page: int, page_size: int = 8, extra_line: str | None = None) -> str:
    courses = _moodle_snapshot_courses(snapshot)
    c = next((x for x in courses if int((x or {}).get('course_id') or 0) == int(course_id)), None)
    if not c:
        return moodle_header(extra_line) + "\nCourse not found in saved snapshot."

    items = c.get("items") if isinstance(c.get("items"), list) else []
    cats = moodle_list_categories(items)

    total = len(cats)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(int(page), pages - 1))
    start = page * page_size
    end = start + page_size
    chunk = cats[start:end]

    name_full = c.get("name") or ""
    code = (c.get("course_code") or "").strip() or _moodle_course_short_name(name_full)
    term = (c.get("term_label") or "").strip()
    overall = moodle_course_overall_grade(c)

    lines: List[str] = [moodle_header(extra_line)]
    lines.append(f"📙 <b>{_h(code)}</b>  <i>({_h(term)})</i>")
    lines.append(f"Course total: <b>{_h(overall)}</b>")
    lines.append(f"\n📂 <b>Categories</b> (page {page+1}/{pages})\n")

    if not cats:
        lines.append("No categories found for this course.")
        return "\n".join(lines)

    for idx, info in chunk:
        label = info.get("label") or "(no category)"
        count = int(info.get("count") or 0)
        fb = int(info.get("with_feedback") or 0)
        pending = int(info.get("pending") or 0)
        tail = []
        if fb:
            tail.append(f"💬{fb}")
        if pending:
            tail.append(f"⏳{pending}")
        suffix = f"  <i>({' '.join(tail)})</i>" if tail else ""
        lines.append(f"• <b>{_h(label)}</b> — {count} item(s){suffix}")

    lines.append("\nTip: tap a category below to open its grade items.")
    return "\n".join(lines)


def build_moodle_course_view(snapshot: dict, *, course_id: int, tab: str, page: int, page_size: int = 8, extra_line: str | None = None) -> str:
    courses = _moodle_snapshot_courses(snapshot)
    c = next((x for x in courses if int((x or {}).get('course_id') or 0) == int(course_id)), None)
    if not c:
        return moodle_header(extra_line) + "\nCourse not found in saved snapshot."

    items = c.get("items") if isinstance(c.get("items"), list) else []

    filtered = moodle_filter_items(items, tab=tab)
    page = max(0, int(page))
    pages = max(1, (len(filtered) + page_size - 1) // page_size)
    page = min(page, pages - 1)
    start = page * page_size
    end = start + page_size
    chunk = filtered[start:end]

    name_full = c.get("name") or ""
    code = (c.get("course_code") or "").strip() or _moodle_course_short_name(name_full)
    term = (c.get("term_label") or "").strip()
    grade_overview = moodle_course_overall_grade(c)
    err = c.get("error")

    # Course-wide stats for quick scanning.
    graded_cnt = len(moodle_filter_items(items, tab="graded"))
    pending_cnt = len(moodle_filter_items(items, tab="pending"))
    feedback_cnt = len(moodle_filter_items(items, tab="feedback"))
    totals_cnt = len(moodle_filter_items(items, tab="totals"))
    nongraded_cnt = len(moodle_filter_items(items, tab="nongraded"))
    problem_cnt = sum(1 for it in items if moodle_item_is_problem(it))

    lines: List[str] = [moodle_header(extra_line)]
    lines.append(f"📙 <b>{_h(code)}</b>  <i>({_h(term)})</i>")
    lines.append(f"Course total: <b>{_h(grade_overview)}</b>")
    lines.append(
        f"\n✅ {graded_cnt}  |  ⏳ {pending_cnt}  |  💬 {feedback_cnt}  |  ⚠️ {problem_cnt}  |  🧮 {totals_cnt}  |  🧩 {nongraded_cnt}"
    )
    short = _moodle_course_short_name(name_full)
    if short and short != code:
        lines.append(_h(short))

    if err:
        lines.append(f"\n⚠️ <b>Course fetch error:</b> {_h(str(err))}")

    tab_key = (tab or "graded").strip().lower()
    tab_title_map = {
        "graded": "Graded items",
        "pending": "Pending / ungraded",
        "feedback": "Items with feedback",
        "totals": "Totals / summaries",
        "nongraded": "Non-graded activities",
        "all": "All items",
    }
    title = tab_title_map.get(tab_key, "Items")
    if tab_key.startswith("cat") and tab_key != "cats":
        try:
            idx = int(tab_key[3:])
            cats = moodle_list_categories(items)
            if 0 <= idx < len(cats):
                title = f"Category: {cats[idx][1].get('label') or 'Items'}"
        except Exception:
            pass

    lines.append(f"\n🧾 <b>{title}</b> (page {page+1}/{pages}):\n")

    if not filtered:
        lines.append("No grade items found for this course yet.")
        return "\n".join(lines)

    for it in chunk:
        name = moodle_clean_item_name((it.get("name") or "").strip())
        val = moodle_item_compact_value(it)
        icon = moodle_item_icon(it)
        cat = _moodle_short_category((it.get("category_path") or "").strip())
        cat_suffix = f"  <i>{_h(cat)}</i>" if (cat and not tab_key.startswith("cat")) else ""
        lines.append(f"• {icon} {_h(name)} — <b>{_h(val)}</b>{cat_suffix}")

    return "\n".join(lines)


def build_moodle_item_detail_view(snapshot: dict, *, course_id: int, item_id: str, extra_line: str | None = None) -> str:
    courses = _moodle_snapshot_courses(snapshot)
    c = next((x for x in courses if int((x or {}).get('course_id') or 0) == int(course_id)), None)
    if not c:
        return moodle_header(extra_line) + "\nCourse not found."

    items = c.get("items") if isinstance(c.get("items"), list) else []
    it = next((x for x in items if str((x or {}).get('item_id') or '') == str(item_id)), None)
    if not it:
        return moodle_header(extra_line) + "\nGrade item not found."

    lines: List[str] = [moodle_header(extra_line)]
    code = (c.get('course_code') or '').strip() or _moodle_course_short_name(c.get('name') or '')
    term = (c.get('term_label') or '').strip()
    lines.append(f"📙 <b>{_h(code)}</b>  <i>({_h(term)})</i>")
    lines.append(_h(_moodle_course_short_name(c.get('name') or '')))

    item_name = moodle_clean_item_name((it.get('name') or '').strip())
    lines.append(f"\n<b>{_h(item_name)}</b>")

    grade = (it.get("grade") or "").strip()
    rng = (it.get("range") or "").strip()
    pct = (it.get("percentage") or "").strip()
    fb = (it.get("feedback") or "").strip()
    cat = (it.get("category_path") or "").strip()
    link = (it.get("link") or "").strip()

    lines.append(f"Status: {moodle_item_icon(it)}")

    if grade:
        lines.append(f"Grade: <b>{_h(_moodle_compact_grade(grade))}</b>")
    if pct:
        lines.append(f"Percentage: <b>{_h(_moodle_compact_pct(pct))}</b>")
    if rng:
        lines.append(f"Range: <b>{_h(rng)}</b>")
    if cat:
        lines.append(f"Category: <i>{_h(cat)}</i>")

    lines.append("\n💬 <b>Feedback</b>")
    if fb:
        # Telegram message limit is 4096 chars; keep some room for other fields.
        if len(fb) > 2400:
            lines.append(_h(fb[:2400].rstrip() + "…"))
            lines.append("\n<i>(Feedback is long, showing the beginning only. Use the link below to read the full text.)</i>")
        else:
            lines.append(_h(fb))
    else:
        lines.append("—")

    if link:
        lines.append(f"\n🔗 {_h(link)}")

    return "\n".join(lines)


def build_moodle_recent_updates_view(
    recent: list[dict] | None,
    *,
    page: int,
    page_size: int = 8,
    extra_line: str | None = None,
) -> str:
    """Human-friendly list of recent changes (derived from diffs)."""
    rec = [x for x in (recent or []) if isinstance(x, dict)]
    total = len(rec)
    page = max(0, int(page))
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages - 1)
    start = page * page_size
    end = start + page_size
    chunk = rec[start:end]

    lines: List[str] = [moodle_header(extra_line), f"🔥 <b>Recent updates</b> (page {page+1}/{pages})\n"]
    if not rec:
        lines.append("No recent updates yet.\n")
        lines.append("Tip: updates appear after a grade/feedback change is detected.")
        return "\n".join(lines)

    for ev in chunk:
        code = (ev.get("course_code") or "").strip() or "(course)"
        term = (ev.get("term_label") or "").strip()
        item = (ev.get("item_name") or "").strip() or "(item)"
        val = (ev.get("new_value") or "").strip() or "—"
        badge = "💬" if ev.get("feedback_changed") else ""
        kind = (ev.get("kind") or "").strip()
        k = f" [{kind}]" if kind else ""
        tail = f" <i>({_h(term)})</i>" if term else ""
        lines.append(f"• <b>{_h(code)}</b>: {_h(item)} — <b>{_h(val)}</b>{_h(k)}{tail}")

        snippet = (ev.get("feedback_snippet") or "").strip()
        if snippet:
            lines.append(f"   💬 {_h(snippet)}")

    lines.append("\nTip: tap an item below to open details.")
    return "\n".join(lines)


# ====== Moodle Diff & Notifications (items + feedback) ======

def _moodle_item_display(it: dict) -> str:
    return moodle_item_compact_value(it)


def compress_moodle_changes_for_recent(changes: List[dict], *, now_iso: str) -> List[dict]:
    """Convert verbose diff output into compact "recent update" events.

    Stored in DB to show quick-access "Recent updates".
    """
    events: List[dict] = []
    for ch in changes or []:
        c = ch.get("course") or {}
        old_it_raw = ch.get("old_item")
        old_it = old_it_raw or {}
        new_it = ch.get("new_item") or {}

        cid = int((c.get("course_id") or 0) or 0)
        iid = str((new_it.get("item_id") or "").strip())
        if cid <= 0 or not iid:
            continue

        code = (c.get("course_code") or "").strip() or _moodle_course_short_name(c.get("name") or "")
        term = (c.get("term_label") or "").strip()
        archived = bool(c.get("archived"))

        item_name = moodle_clean_item_name((new_it.get("name") or "").strip())
        new_val = _moodle_item_display(new_it)
        old_val = _moodle_item_display(old_it) if old_it_raw is not None else "—"

        old_fb = (old_it.get("feedback") or "").strip() if old_it_raw is not None else ""
        new_fb = (new_it.get("feedback") or "").strip()
        feedback_changed = bool(new_fb and (new_fb != old_fb))

        grade_changed = bool(new_val and new_val != "—" and (old_val != new_val))
        if old_it_raw is None:
            kind = "new"
        elif grade_changed and feedback_changed:
            kind = "grade+feedback"
        elif grade_changed:
            kind = "grade"
        elif feedback_changed:
            kind = "feedback"
        else:
            kind = ""

        snippet = ""
        if feedback_changed:
            snippet = new_fb
            if len(snippet) > 120:
                snippet = snippet[:120].rstrip() + "…"

        events.append(
            {
                "ts": now_iso,
                "course_id": cid,
                "course_code": code,
                "term_label": term,
                "archived": archived,
                "item_id": iid,
                "item_name": item_name,
                "new_value": new_val,
                "feedback_changed": feedback_changed,
                "feedback_snippet": snippet,
                "kind": kind,
            }
        )

    return events


def find_new_or_changed_moodle_items(prev_snapshot_json: Optional[str], new_snapshot: dict) -> List[dict]:
    """Return a list of per-item changes for Moodle (grade and/or feedback)."""
    prev = parse_snapshot(prev_snapshot_json) if prev_snapshot_json else {}
    prev_courses = {int((c or {}).get("course_id") or 0): (c or {}) for c in (prev or {}).get("courses", []) if isinstance(c, dict)}
    new_courses = {int((c or {}).get("course_id") or 0): (c or {}) for c in (new_snapshot or {}).get("courses", []) if isinstance(c, dict)}

    changes: List[dict] = []

    for cid, c in new_courses.items():
        old_c = prev_courses.get(cid, {})
        old_items = {str((it or {}).get("item_id") or ""): (it or {}) for it in (old_c.get("items") or []) if isinstance(it, dict)}
        for it in (c.get("items") or []):
            if not isinstance(it, dict):
                continue
            iid = str(it.get("item_id") or "")
            if not iid:
                continue

            old_it = old_items.get(iid)
            if old_it is None:
                # New item appears. Notify only if it has something meaningful.
                if (it.get("grade") or it.get("percentage") or it.get("feedback")):
                    changes.append({"course": c, "old_item": None, "new_item": it})
                continue

            # Detect changes.
            grade_changed = (it.get("grade") or "") != (old_it.get("grade") or "") or (it.get("percentage") or "") != (old_it.get("percentage") or "")
            feedback_changed = (it.get("feedback") or "") != (old_it.get("feedback") or "")

            # Only notify on meaningful new values.
            if grade_changed and (it.get("grade") or it.get("percentage")):
                changes.append({"course": c, "old_item": old_it, "new_item": it})
                continue

            if feedback_changed and (it.get("feedback") or ""):
                changes.append({"course": c, "old_item": old_it, "new_item": it})
                continue

    return changes


def format_moodle_item_change_notification(changes: List[dict]) -> str:
    if not changes:
        return ""

    # Group by course_id.
    grouped: Dict[int, List[dict]] = {}
    for ch in changes:
        c = ch.get("course") or {}
        cid = int((c.get("course_id") or 0))
        grouped.setdefault(cid, []).append(ch)

    lines: List[str] = ["📙 <b>Moodle update</b>\n"]

    for cid, arr in grouped.items():
        c = (arr[0].get("course") or {})
        code = (c.get("course_code") or "").strip() or _moodle_course_short_name(c.get("name") or "")
        term = (c.get("term_label") or "").strip()
        lines.append(f"• <b>{_h(code)}</b> <i>({_h(term)})</i>")

        for ch in arr[:8]:  # keep message short, remaining changes will be in next polling cycle anyway
            old_it = ch.get("old_item") or {}
            new_it = ch.get("new_item") or {}
            name = moodle_clean_item_name((new_it.get("name") or "").strip())

            old_disp = _moodle_item_display(old_it) if old_it else "—"
            new_disp = _moodle_item_display(new_it)

            parts = []
            if old_it:
                if old_disp != new_disp and new_disp != "—":
                    parts.append(f"{_h(old_disp)} → <b>{_h(new_disp)}</b>")
            else:
                parts.append(f"new: <b>{_h(new_disp)}</b>")

            # Feedback change (show snippet)
            old_fb = (old_it.get("feedback") or "").strip()
            new_fb = (new_it.get("feedback") or "").strip()
            if new_fb and new_fb != old_fb:
                snippet = new_fb
                if len(snippet) > 120:
                    snippet = snippet[:120].rstrip() + "…"
                parts.append(f"💬 {_h(snippet)}")

            if not parts:
                continue

            lines.append(f"   - <b>{_h(name)}</b>: " + " | ".join(parts))

        lines.append("")

    return "\n".join(lines).strip()

# ====== FIC Diff & Notification Formatting ======

def _flatten_grades_map(grades_map: dict) -> Dict[Tuple[str, str], str]:
    flat: Dict[Tuple[str, str], str] = {}
    if not isinstance(grades_map, dict):
        return flat

    for sem, inner in grades_map.items():
        inner = inner or {}
        for code, grade in inner.items():
            flat[(str(sem), str(code))] = (grade or "").strip()

    return flat


def find_new_or_changed_fic_grades(prev_snapshot_json: Optional[str], new_map: dict) -> List[Tuple[str, str]]:
    prev_map = parse_snapshot(prev_snapshot_json)
    old_flat = _flatten_grades_map(prev_map)
    new_flat = _flatten_grades_map(new_map)

    changes: List[Tuple[str, str]] = []
    for (sem, code), new_grade in new_flat.items():
        if not new_grade:
            continue
        old_grade = old_flat.get((sem, code), "")
        if old_grade != new_grade:
            changes.append((code, new_grade))

    changes.sort(key=lambda x: (x[0], x[1]))
    return changes


def format_fic_new_grade_notification(changes: List[Tuple[str, str]]) -> str:
    if len(changes) == 1:
        head = "📗 <b>New grade</b>"
    else:
        head = "📗 <b>New grades</b>"

    lines = [head] + [f"  {code}: {grade}" for code, grade in changes]
    return "\n".join(lines)


def find_new_or_changed_moodle_grades(prev_snapshot_json: Optional[str], new_map: dict) -> List[Tuple[str, str]]:
    # Same diff rules as FIC: notify only when a grade becomes non-empty or changes.
    prev_map = parse_snapshot(prev_snapshot_json)
    old_flat = _flatten_grades_map(prev_map)
    new_flat = _flatten_grades_map(new_map)

    changes: List[Tuple[str, str]] = []
    for (sem, code), new_grade in new_flat.items():
        if not new_grade:
            continue
        old_grade = old_flat.get((sem, code), "")
        if old_grade != new_grade:
            changes.append((code, new_grade))

    changes.sort(key=lambda x: (x[0], x[1]))
    return changes


def format_moodle_new_grade_notification(changes: List[Tuple[str, str]]) -> str:
    if len(changes) == 1:
        head = "📙 <b>New Moodle grade</b>"
    else:
        head = "📙 <b>New Moodle grades</b>"
    lines = [head] + [f"  {code}: {grade}" for code, grade in changes]
    return "\n".join(lines)
