from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup


def _clean(x: str | None) -> str:
    return (x or "").replace("\xa0", " ").strip()


_DASHES = {"-", "–", "—"}


def _split_course_label(course_name: str) -> Tuple[str, str]:
    """Split a Moodle course title into (term_label, course_code).

    Expected examples:
      - "FIC 202503 MACM101_CHAB (archived) Discrete Mathematics I (archived)"
      - "FIC 202503 MACMT_YWELDESEL Discrete Mathematics Tutorial"

    Returns:
      term_label: "FIC 202503" (or "Moodle" fallback)
      course_code: "MACM101" (best-effort)
    """

    s = _clean(course_name)
    if not s:
        return "Moodle", ""

    # Normalize spacing
    s = re.sub(r"\s+", " ", s)
    up = s.upper()

    # Primary pattern: FIC YYYYTT + token like CMPT135_YEJI
    m = re.match(r"^(FIC)\s+(\d{6})\s+([^\s]+)", up)
    if m:
        term_label = f"{m.group(1)} {m.group(2)}"
        raw = m.group(3)
        code = raw.split("_")[0]
        code = re.sub(r"[^A-Z0-9]", "", code)
        return term_label, code

    # Fallback: find a course code anywhere (e.g., CMPT 135, ECON1034)
    m2 = re.search(r"\b([A-Z]{2,6}\d{2,4})\b", up)
    code = m2.group(1) if m2 else ""
    return "Moodle", code


def moodle_overview_has_not_enrolled_message(html: str) -> bool:
    """Sometimes Moodle shows the 'not enrolled' notice on first visit after login."""
    h = (html or "")
    # Moodle wording can vary slightly and HTML exports may inject extra whitespace.
    hl = " ".join(h.lower().split())
    if "not enrolled" in hl and "courses" in hl:
        return True
    return "you are not enrolled in, nor teaching any courses on this site" in hl


@dataclass(frozen=True)
class MoodleCourseOverview:
    course_id: int
    name: str
    url: str
    grade: str
    archived: bool
    term_label: str
    course_code: str


@dataclass(frozen=True)
class MoodleGradeItem:
    item_id: str
    name: str
    grade: str
    range: str
    percentage: str
    feedback: str
    link: Optional[str]
    level: int
    category_path: str


def parse_moodle_overview_courses(html: str, empty_grade: str = "") -> List[MoodleCourseOverview]:
    """Parse Moodle grade overview page into a list of courses."""
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table", id="overview-grade")
    if not table:
        return []

    out: List[MoodleCourseOverview] = []
    seen_ids: set[int] = set()

    for tr in table.find_all("tr"):
        c0 = tr.find(["th", "td"], class_=lambda c: c and "c0" in str(c).split())
        c1 = tr.find("td", class_=lambda c: c and "c1" in str(c).split())
        if not c0 or not c1:
            continue

        # Moodle overview has a header row. Skip it reliably.
        header_text = _clean(c0.get_text(" ", strip=True)).lower()
        if header_text in {"course name", "course name grade", "course name\xa0grade"}:
            continue

        a = c0.find("a")
        url = (a.get("href") if a else "") or ""
        if not url or url in {"#", "/"}:
            # Some pages can contain rows/links with empty href; ignore them.
            continue

        # We only care about real course grade report links.
        if "course/user.php" not in url:
            continue

        course_name = _clean(a.get_text(" ", strip=True) if a else c0.get_text(" ", strip=True))
        if not course_name:
            continue

        course_id = 0
        try:
            q = parse_qs(urlparse(url).query)
            course_id = int((q.get("id") or ["0"])[0])
        except Exception:
            course_id = 0
        if course_id <= 0:
            continue
        if course_id in seen_ids:
            continue
        seen_ids.add(course_id)

        # Grade text (can be '-' or empty).
        grade = _clean(c1.get_text(" ", strip=True))
        if grade in _DASHES:
            grade = empty_grade
        # Safety: if HTML is malformed and grade cell accidentally contains course titles,
        # treat it as empty. (We've seen this in some saved HTML exports.)
        if "FIC" in grade and "course/user.php" not in grade:
            grade = empty_grade

        term, code = _split_course_label(course_name)
        # A course without a recognizable code should be treated as archived.
        # (User requirement: code-less courses always live in Archived.)
        archived = "(archived)" in course_name.lower() or (not bool(code))

        out.append(
            MoodleCourseOverview(
                course_id=course_id,
                name=course_name,
                url=url,
                grade=grade,
                archived=archived,
                term_label=term,
                # Keep empty when not detected; UI will fall back to short name.
                course_code=code,
            )
        )

    return out


def parse_moodle_overview(html: str, empty_grade: str = "") -> Dict[str, Dict[str, str]]:
    """Parse Moodle grade overview page.

    Backwards-compatible compact format:
      {term_label: {course_code: grade_text}}
    """
    result: Dict[str, Dict[str, str]] = {}
    for c in parse_moodle_overview_courses(html, empty_grade=empty_grade):
        key = c.course_code or f"course_{c.course_id}"
        result.setdefault(c.term_label, {})[key] = c.grade
    return result


def _row_level(class_list: List[str] | None) -> int:
    cls = class_list or []
    for x in cls:
        m = re.match(r"level(\d+)", x)
        if m:
            return int(m.group(1))
    return 0


def _strip_expand_collapse_tokens(s: str) -> str:
    s = re.sub(r"\b(Collapse|Expand)\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_moodle_course_report(html: str) -> List[MoodleGradeItem]:
    """Parse a course 'Activity report (grade)' page (course/user.php?mode=grade).

    Moodle pages are not fully consistent:
      - Some courses show a 'Grade' column, others show only Range/Percentage/Feedback.
      - Rows can be category headers (collapsible) or grade items/aggregations.

    We return a flat list of grade items/aggregations, each with:
      - grade (may be empty)
      - range, percentage, feedback
      - category_path inferred from category row metadata (best-effort)
    """
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table", class_=lambda c: c and "user-grade" in str(c).split())
    if not table:
        return []

    # Header -> column mapping.
    header_tr = None
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if ths and all("header" in (th.get("class") or []) for th in ths):
            header_tr = tr
            break
    if header_tr is None:
        header_tr = table.find("tr")

    header_ths = (header_tr.find_all("th") if header_tr else [])
    # Skip the first header cell ("Grade item").
    col_keys: List[Optional[str]] = []
    for th in header_ths[1:]:
        t = _clean(th.get_text(" ", strip=True)).lower()
        if t.startswith("grade") and "item" not in t:
            col_keys.append("grade")
        elif "range" in t:
            col_keys.append("range")
        elif "percentage" in t:
            col_keys.append("percentage")
        elif "feedback" in t:
            col_keys.append("feedback")
        else:
            col_keys.append(None)

    # Category rows provide names for cat_#### ids.
    cat_info: Dict[str, Tuple[int, str]] = {}  # cat_id -> (level, name)
    for tr in table.find_all("tr"):
        th = tr.find("th")
        if not th:
            continue
        tid = (th.get("id") or "")
        if not tid.startswith("cat_"):
            continue
        classes = th.get("class") or []
        if "category" not in classes:
            continue
        m = re.match(r"cat_(\d+)", tid)
        if not m:
            continue
        cat_id = m.group(1)
        name = _strip_expand_collapse_tokens(_clean(th.get_text(" ", strip=True)))
        level = _row_level(classes)
        if name:
            cat_info[cat_id] = (level, name)

    out: List[MoodleGradeItem] = []

    for tr in table.find_all("tr"):
        tr_classes = tr.get("class") or []
        if "spacer" in tr_classes:
            continue

        th = tr.find("th")
        if not th:
            continue

        # Skip header row.
        if "header" in (th.get("class") or []):
            continue

        # Skip category headers; items live in subsequent rows.
        tid = (th.get("id") or "")
        if tid.startswith("cat_") and "category" in (th.get("class") or []):
            continue

        # Extract stable item_id.
        item_id = ""
        m = re.match(r"^(row_\d+)", tid)
        if m:
            item_id = m.group(1)
        else:
            # Fallback: hash name + classes.
            raw = (tid or "") + "|" + "|".join(tr_classes) + "|" + _clean(th.get_text(" ", strip=True))
            item_id = "row_" + sha1(raw.encode("utf-8", "ignore")).hexdigest()[:10]

        # Grade item name (prefer gradeitemheader title).
        hdr = th.find(class_="gradeitemheader")
        if hdr:
            name = _clean(hdr.get("title") or hdr.get_text(" ", strip=True))
        else:
            name = _clean(th.get_text(" ", strip=True))
        name = re.sub(r"\s+", " ", name).strip()

        link = None
        if hdr and getattr(hdr, "name", "") == "a":
            link = hdr.get("href") or None

        level = _row_level(th.get("class") or [])

        # Category path inferred from row classes like "cat_17006 cat_17011".
        cats: List[Tuple[int, str]] = []
        for c in tr_classes:
            m = re.match(r"cat_(\d+)", c)
            if not m:
                continue
            cid = m.group(1)
            if cid in cat_info:
                cats.append(cat_info[cid])
        cats_sorted = [n for _, n in sorted(cats, key=lambda t: t[0])]
        category_path = " > ".join(cats_sorted)

        # Values by column order.
        grade = ""
        rng = ""
        pct = ""
        fb = ""

        tds = tr.find_all("td")
        for i, td in enumerate(tds):
            key = col_keys[i] if i < len(col_keys) else None
            if not key:
                continue
            val = _clean(td.get_text(" ", strip=True))
            if val in _DASHES:
                val = ""
            if key == "grade":
                grade = val
            elif key == "range":
                rng = val
            elif key == "percentage":
                pct = val
            elif key == "feedback":
                fb = val

        out.append(
            MoodleGradeItem(
                item_id=item_id,
                name=name,
                grade=grade,
                range=rng,
                percentage=pct,
                feedback=fb,
                link=link,
                level=level,
                category_path=category_path,
            )
        )

    return out
