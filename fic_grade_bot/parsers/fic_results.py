from typing import Dict
from bs4 import BeautifulSoup

def parse_results(html: str, empty_grade: str = "") -> Dict[str, Dict[str, str]]:
    """
    Parser for the "Results" table on learning.fraseric.ca.
    Returns: {semester: {course_code: grade}}
    """

    def clean(x) -> str:
        return (x or "").strip()


    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="data-table")
    result: Dict[str, Dict[str, str]] = {}

    if not table:
        return result

    tbody = table.find("tbody")
    if not tbody:
        return result

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        semester = clean(tds[0].get_text())
        code = clean(tds[1].get_text())
        grade = clean(tds[4].get_text())


        if not semester or not code:
            continue
        if not grade:
            grade = empty_grade


        result.setdefault(semester, {})[code] = grade

    return result