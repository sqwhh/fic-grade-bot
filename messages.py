# messages.py
"""User-facing message builders.

Only FIC grades + GPA logic is kept.
(Moodle and Enrollment message logic was removed.)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from utils import parse_snapshot


# ====== Course Credits & GPA Data ======

def get_course_credits(course_code: str) -> int:
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
        'INDG201': 3, 'INS101': 0, 'INS102': 0, 'INTG100': 0,
        'IS101': 3, 'IUW100': 0, 'LBST101': 3, 'LING110': 3,
        'LING111': 3, 'LING200': 3, 'LING220': 3, 'MACM101': 3,
        'MATH100': 3, 'MATH151': 3, 'MATH152': 3, 'MATH157': 3,
        'MATH232': 3, 'MTH099': 0, 'MTH101': 0, 'MTH103': 0,
        'PHIL105': 3, 'PHL120': 0, 'PHYS100': 3, 'PHYS140': 4,
        'PHYS1141': 1, 'PHYS141': 4, 'POL100': 3, 'POL141': 3,
        'POL151': 3, 'POL231': 3, 'POL232': 3, 'PSYC100': 3,
        'PSYC102': 3, 'PSYC109': 3, 'PSYC201': 4, 'PSYC250': 3,
        'REM100': 3, 'STAT203': 3, 'UNI101': 0, 'WIS100': 0,
        'WL101': 3, 'WL201': 3,
    }
    return courses.get(course_code, 0)


GRADE_POINTS = {
    "A+": 4.33,
    "A": 4.0,
    "A-": 3.67,
    "B+": 3.33,
    "B": 3.0,
    "B-": 2.67,
    "C+": 2.33,
    "C": 2.0,
    "C-": 1.67,
    "D": 1.0,
}


def grade_to_points(grade: str) -> float:
    return GRADE_POINTS.get(grade.strip(), 0.0) if grade else 0.0


# ====== FIC Message Formatting ======

def format_grades_compact(grades_map: Dict[str, Dict[str, str]]) -> str:
    if not grades_map:
        return "No saved grades yet. Press “Force refresh” to fetch."

    lines: List[str] = []
    sems = sorted(grades_map.keys())
    for i, sem in enumerate(sems):
        lines.append(f"🗓 <b>{sem}</b>")
        inner = grades_map.get(sem) or {}
        for code, grade in sorted(inner.items()):
            g = grade if grade else "—"
            lines.append(f"  • {code}: {g}")
        if i < len(sems) - 1:
            lines.append("")
    return "\n".join(lines)


def format_gpa_report_compact(grades_map: Dict[str, Dict[str, str]]) -> str:
    if not grades_map:
        return "No graded courses yet."

    lines = ["📊 GPA Calculation"]

    total_best_points = 0.0
    total_best_credits = 0

    best_pts_by_code: Dict[str, float] = {}
    credits_by_code: Dict[str, int] = {}

    sems = sorted(grades_map.keys())
    for sem in sems:
        sem_points = 0.0
        sem_credits = 0

        lines.append(f"\n🗓 <b>{sem}</b>")
        for code, grade in sorted((grades_map.get(sem) or {}).items()):
            cr = get_course_credits(code)
            pt = grade_to_points(grade)
            gtxt = grade if grade else "—"
            lines.append(f"  • {code} ({cr} cr): {gtxt}")

            if grade:
                sem_points += pt * cr
                sem_credits += cr

                # Use the best attempt for cumulative GPA.
                if code not in best_pts_by_code or pt > best_pts_by_code[code]:
                    best_pts_by_code[code] = pt
                    credits_by_code[code] = cr

        sem_gpa = (sem_points / sem_credits) if sem_credits > 0 else 0.0
        lines.append(f"  ➤ Closed credits: {sem_credits} | GPA: {sem_gpa:.3f}")

    for code, pt in best_pts_by_code.items():
        cr = credits_by_code.get(code, 0)
        total_best_points += pt * cr
        total_best_credits += cr

    cum_gpa = (total_best_points / total_best_credits) if total_best_credits > 0 else 0.0
    lines.append(f"\n🔢 Total closed credits: {total_best_credits}")
    lines.append(f"🏁 Cumulative GPA: {cum_gpa:.3f}")

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
