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
from typing import Dict, List, Optional, Tuple

from utils import parse_snapshot


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

def fic_header() -> str:
    return "<b>📗 FIC grades</b>\n"


def build_fic_grades_view(grades_map: dict, footer: str | None = None) -> str:
    body = format_grades_compact(grades_map or {})
    parts = [fic_header(), body]
    if footer:
        parts.append(f"\n{footer}")
    return "\n".join(parts)


def build_fic_gpa_view(grades_map: dict, footer: str | None = None) -> str:
    body = format_gpa_report_compact(grades_map or {})
    parts = [fic_header(), body]
    if footer:
        parts.append(f"\n{footer}")
    return "\n".join(parts)


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
