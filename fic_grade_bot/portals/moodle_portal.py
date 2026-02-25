from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Dict
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from ..constants import MOODLE_BASE, MOODLE_LOGIN_URL, MOODLE_LOGOUT_URL, MOODLE_OVERVIEW_URL
from ..config import MOODLE_ACTIVE_TERMS
from ..parsers.moodle_results import (
    moodle_overview_has_not_enrolled_message,
    parse_moodle_course_report,
    parse_moodle_overview,
    parse_moodle_overview_courses,
)
from ..browser.playwright_manager import get_playwright_instance
from ..browser.session import PortalSession
from ..utils import current_fic_term_code, fic_term_prev, parse_fic_term_code


class MoodleClient:
    """Client for moodle.fraseric.ca.

    Strategy:
    1) Fast path: Playwright APIRequestContext (no browser UI) + auto-post SAML forms.
    2) Fallback: real headless browser navigation for SSO pages that require JS.
    """

    def __init__(self, session: PortalSession):
        self.sess = session

    def _normalize_course_url(self, url: str) -> str:
        """Ensure course URLs are absolute and look valid."""
        u = (url or "").strip()
        if not u:
            return ""
        if u.startswith("/"):
            return urljoin(MOODLE_BASE, u)
        if u.startswith("http://") or u.startswith("https://"):
            return u
        return urljoin(MOODLE_BASE + "/", u)

    def _sanitize_courses(self, courses):
        """Drop malformed/empty courses and dedupe by course_id."""
        out = []
        seen = set()
        for c in (courses or []):
            try:
                cid = int(getattr(c, "course_id", 0) or 0)
            except Exception:
                cid = 0
            url = self._normalize_course_url(getattr(c, "url", "") or "")
            name = (getattr(c, "name", "") or "").strip()
            if cid <= 0 or not url or not name:
                continue
            if "course/user.php" not in url:
                continue
            if cid in seen:
                continue
            seen.add(cid)
            # Patch the object with normalized url (dataclass is frozen, so we just keep a side-map).
            out.append((c, url))
        return out

    def _derive_overview_grade(self, overview_grade: str, items: list[dict]) -> str:
        """If overview grade is missing, try to derive it from the 'Course total' row."""
        g = (overview_grade or "").strip()
        if g:
            return g
        for it in items or []:
            try:
                if str((it or {}).get("name") or "").strip().lower() == "course total":
                    # Prefer grade, otherwise percentage.
                    v = str((it or {}).get("grade") or "").strip() or str((it or {}).get("percentage") or "").strip()
                    if v:
                        return v
            except Exception:
                continue
        return g

    def _apply_archive_policy(self, base_archived: bool, term_label: str, course_code: str) -> bool:
        """Decide if a course should be shown in Archived.

        Rules:
          1) If Moodle marks it as archived OR we cannot detect a course code -> archived.
          2) Otherwise, keep only the most recent FIC term(s) as Active.
             Everything older moves to Archived (even if Moodle does not label it archived).
        """
        # Requirement: courses without a recognizable code always live in Archived.
        if not (course_code or "").strip():
            return True
        if base_archived:
            return True

        tc = parse_fic_term_code(term_label)
        if tc <= 0:
            # Non-FIC terms (or unknown labels) are treated as Archived.
            return True

        cur = current_fic_term_code()
        keep = int(MOODLE_ACTIVE_TERMS or 1)
        if keep < 1:
            keep = 1
        if keep > 6:
            keep = 6

        oldest_active = fic_term_prev(cur, steps=keep - 1)
        return tc < oldest_active

    # ---------------------------
    # Helpers (request context)
    # ---------------------------

    async def _submit_autopost_form(self, html: str, current_url: str):
        """Submit auto-post HTML forms (common in SAML flows)."""
        soup = BeautifulSoup(html or "", "html.parser")
        for form in soup.find_all("form"):
            # Typical SAML handoff uses SAMLResponse + RelayState.
            has_saml = bool(form.find("input", {"name": "SAMLResponse"}))
            has_relay = bool(form.find("input", {"name": "RelayState"}))
            if not (has_saml or has_relay):
                continue

            action = (form.get("action") or "").strip()
            action_url = urljoin(current_url, action) if action else current_url

            payload: Dict[str, str] = {}
            for inp in form.find_all("input"):
                name = (inp.get("name") or "").strip()
                if not name:
                    continue
                payload[name] = (inp.get("value") or "")

            return await self.sess.req.post(action_url, form=payload)
        return None

    def _find_login_form_fields(self, html: str):
        """Best-effort detect a username + password form in HTML and return (action_url, payload_template, user_field, pass_field)."""
        soup = BeautifulSoup(html or "", "html.parser")

        # Prefer a form that contains a password input.
        forms = soup.find_all("form")
        best = None
        for f in forms:
            if f.find("input", {"type": "password"}):
                best = f
                break
        if best is None and forms:
            best = forms[0]
        if best is None:
            return None

        action = (best.get("action") or "").strip()
        method = (best.get("method") or "post").strip().lower()

        inputs = best.find_all("input")
        payload: Dict[str, str] = {}
        user_field = None
        pass_field = None

        for inp in inputs:
            name = (inp.get("name") or "").strip()
            if not name:
                continue
            itype = (inp.get("type") or "").strip().lower()
            val = inp.get("value") or ""
            payload[name] = val

            if itype == "password":
                pass_field = name
            elif itype in {"text", "email", ""}:
                # Heuristic: names / ids containing user/email/login
                nid = f"{name} {(inp.get('id') or '')} {(inp.get('autocomplete') or '')}".lower()
                if any(k in nid for k in ("user", "email", "login", "name")):
                    user_field = name

        # If we still don't know user_field, take the first non-hidden, non-password input.
        if user_field is None:
            for inp in inputs:
                name = (inp.get("name") or "").strip()
                if not name:
                    continue
                itype = (inp.get("type") or "").strip().lower()
                if itype in {"text", "email"}:
                    user_field = name
                    break

        if pass_field is None:
            return None

        return action, method, payload, user_field, pass_field

    async def _login_via_learning_sso_requests(self, redirect_url: str, username: str, password: str) -> None:
        """Handle Moodle SSO redirect to learning.fraseric.ca via request context.

        Works when the IdP login page is a simple HTML form and/or returns SAML auto-post.
        """
        # Fetch the redirect page (it may already include an auto-post form).
        r = await self.sess.req.get(redirect_url)
        for _ in range(10):
            final_url = (r.url or "").strip()
            if final_url.startswith(MOODLE_BASE):
                return

            html = await r.text()

            # 1) If it's an auto-post form (SAMLResponse), submit it.
            nxt = await self._submit_autopost_form(html, final_url or redirect_url)
            if nxt is not None:
                r = nxt
                continue

            # 2) Otherwise, try to detect a login form and submit credentials.
            form_info = self._find_login_form_fields(html)
            if form_info:
                action, method, payload, user_field, pass_field = form_info
                action_url = urljoin(final_url or redirect_url, action) if action else (final_url or redirect_url)

                if user_field:
                    payload[user_field] = username
                payload[pass_field] = password

                if method == "get":
                    r = await self.sess.req.get(action_url, params=payload)
                else:
                    r = await self.sess.req.post(action_url, form=payload)
                continue

            break

        # Last attempt: if logged into learning, requesting overview again may complete SSO.
        r2 = await self.sess.req.get(MOODLE_OVERVIEW_URL)
        if ((r2.url or "").strip()).startswith(MOODLE_BASE):
            return

        raise RuntimeError(f"Moodle SSO login did not complete (stuck at: {((r2.url or '').strip())})")

    # ---------------------------
    # Helpers (browser fallback)
    # ---------------------------

    async def _first_visible(self, page, selectors, timeout_ms: int = 800):
        for sel in selectors:
            loc = page.locator(sel)
            try:
                if await loc.count() > 0:
                    await loc.first.wait_for(state="visible", timeout=timeout_ms)
                    return loc.first
            except Exception:
                continue
        return None

    async def _maybe_submit_login(self, page, username: str, password: str) -> bool:
        """Try to fill a login form on the current page. Returns True if we clicked/pressed submit."""
        # Step 1: Microsoft-like email-first flow
        email = await self._first_visible(page, [
            'input[type="email"]',
            'input[name="loginfmt"]',
            'input[name="Email"]',
        ])
        if email:
            try:
                await email.fill(username)
                btn = await self._first_visible(page, [
                    'input[type="submit"]',
                    'button[type="submit"]',
                    'button:has-text("Next")',
                    'button:has-text("Continue")',
                ])
                if btn:
                    await btn.click()
                    return True
            except Exception:
                pass

        # Step 2: standard username/password form
        user = await self._first_visible(page, [
            'input[name="username"]',
            'input#username',
            'input[name="user"]',
            'input[name="j_username"]',
            'input[type="text"]',
        ])
        pwd = await self._first_visible(page, [
            'input[name="password"]',
            'input#password',
            'input[name="pass"]',
            'input[name="j_password"]',
            'input[type="password"]',
        ])

        if not pwd:
            return False

        try:
            if user:
                await user.fill(username)
            await pwd.fill(password)

            btn = await self._first_visible(page, [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
            ])
            if btn:
                await btn.click()
            else:
                await pwd.press("Enter")
            return True
        except Exception:
            return False

    async def _maybe_handle_prompts(self, page) -> bool:
        """Handle common prompts like 'Stay signed in?'. Returns True if we clicked something."""
        # Microsoft prompt
        btn = await self._first_visible(page, [
            'button:has-text("No")',
            'input[type="button"][value="No"]',
            'input[type="submit"][value="No"]',
            'button:has-text("Continue")',
        ], timeout_ms=500)
        if btn:
            try:
                await btn.click()
                return True
            except Exception:
                return False
        return False

    async def _get_overview_html_via_browser(self, username: str, password: str) -> str:
        """Headless-browser fallback for Moodle SSO."""
        pw = await get_playwright_instance()
        try:
            browser = await pw.chromium.launch(headless=True)
        except PlaywrightError as e:
            # Helpful message for local runs without installed browsers.
            raise RuntimeError(
                "Playwright browser is not installed. Run: `python -m playwright install chromium`"
            ) from e

        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(MOODLE_OVERVIEW_URL, wait_until="domcontentloaded", timeout=45000)

            # Loop: try to login / accept prompts until we land on Moodle overview.
            for _ in range(30):
                url = page.url or ""
                if url.startswith(MOODLE_BASE) and "/grade/report/overview/" in url:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightTimeoutError:
                        pass
                    return await page.content()

                # Sometimes we land on Moodle base but not the overview yet.
                if url.startswith(MOODLE_BASE) and "moodle.fraseric.ca" in url:
                    try:
                        await page.goto(MOODLE_OVERVIEW_URL, wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        pass

                did = await self._maybe_submit_login(page, username, password)
                did = (await self._maybe_handle_prompts(page)) or did

                # If nothing to do, just wait for redirects.
                await page.wait_for_timeout(1200)

            raise RuntimeError(f"Moodle SSO login did not complete (stuck at: {page.url})")
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

    
    async def _get_full_snapshot_via_browser(self, username: str, password: str) -> dict:
        """Headless-browser fallback that fetches overview + each course report."""
        pw = await get_playwright_instance()
        try:
            browser = await pw.chromium.launch(headless=True)
        except PlaywrightError as e:
            raise RuntimeError(
                "Playwright browser is not installed. Run: `python -m playwright install chromium`"
            ) from e

        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(MOODLE_OVERVIEW_URL, wait_until="domcontentloaded", timeout=45000)

            # Login loop.
            for _ in range(30):
                url = page.url or ""
                if url.startswith(MOODLE_BASE) and "/grade/report/overview/" in url:
                    break

                if url.startswith(MOODLE_BASE) and "moodle.fraseric.ca" in url:
                    try:
                        await page.goto(MOODLE_OVERVIEW_URL, wait_until="domcontentloaded", timeout=45000)
                    except Exception:
                        pass

                did = await self._maybe_submit_login(page, username, password)
                did = (await self._maybe_handle_prompts(page)) or did
                await page.wait_for_timeout(1200)

            if not ((page.url or "").startswith(MOODLE_BASE) and "/grade/report/overview/" in (page.url or "")):
                raise RuntimeError(f"Moodle SSO login did not complete (stuck at: {page.url})")

            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            overview_html = await page.content()

            # Some accounts/pages show the 'not enrolled' notice once, then the table appears on refresh.
            # Retry a few times.
            for _ in range(3):
                if not moodle_overview_has_not_enrolled_message(overview_html):
                    break
                await page.wait_for_timeout(800)
                await page.goto(MOODLE_OVERVIEW_URL, wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    pass
                overview_html = await page.content()

            raw_courses = parse_moodle_overview_courses(overview_html)
            courses = self._sanitize_courses(raw_courses)

            snapshot = {"courses": [], "fetched_at": datetime.now(timezone.utc).isoformat()}

            for c, c_url in courses:
                archived_flag = self._apply_archive_policy(bool(getattr(c, "archived", False)), getattr(c, "term_label", ""), getattr(c, "course_code", ""))
                try:
                    if not c_url:
                        raise RuntimeError("Invalid course URL")
                    await page.goto(c_url, wait_until="domcontentloaded", timeout=45000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except PlaywrightTimeoutError:
                        pass
                    report_html = await page.content()
                    items = parse_moodle_course_report(report_html)
                except Exception as e:
                    # Attach error on course record so UI can show it.
                    snapshot["courses"].append(
                        {
                            "course_id": c.course_id,
                            "name": c.name,
                            "url": c_url,
                            "grade_overview": c.grade,
                            "archived": archived_flag,
                            "term_label": c.term_label,
                            "course_code": c.course_code,
                            "items": [],
                            "error": str(e),
                        }
                    )
                    continue

                # Success path: store parsed items.
                items_dicts = [item.__dict__ for item in (items or [])]
                derived_grade = self._derive_overview_grade(c.grade, items_dicts)
                snapshot["courses"].append(
                    {
                        "course_id": c.course_id,
                        "name": c.name,
                        "url": c_url,
                        "grade_overview": derived_grade,
                        "archived": archived_flag,
                        "term_label": c.term_label,
                        "course_code": c.course_code,
                        "items": items_dicts,
                        "error": None,
                    }
                )

            return snapshot
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

# ---------------------------
    # Public API
    # ---------------------------

    async def login(self, username: str, password: str) -> None:
        await self.sess.start()

        # Start from the overview page (it triggers SSO if needed).
        r0 = await self.sess.req.get(MOODLE_OVERVIEW_URL)
        final_url = (r0.url or "").strip()

        if final_url.startswith(MOODLE_BASE):
            return

        # SSO flow: redirect to learning.fraseric.ca with SAMLRequest.
        if "learning.fraseric.ca" in final_url and "/user/login" in urlsplit(final_url).path:
            await self._login_via_learning_sso_requests(final_url, username, password)
            return

        # Fallback: classic Moodle login with logintoken.
        r_login = await self.sess.req.get(MOODLE_LOGIN_URL)
        html0 = await r_login.text()
        soup = BeautifulSoup(html0, "html.parser")
        tok_el = soup.find("input", {"name": "logintoken"})
        token = tok_el.get("value") if tok_el else None

        form = {"username": username, "password": password}
        if token:
            form["logintoken"] = token

        r = await self.sess.req.post(MOODLE_LOGIN_URL, form=form)
        final_url2 = (r.url or "").strip()

        parts = urlsplit(final_url2)
        if "/login/index.php" in parts.path:
            body = await r.text()
            if "loginerrormessage" in body.lower() or "invalidlogin" in body.lower():
                raise ValueError("Invalid username or password.")
            raise ValueError("Invalid username or password.")

        if "learning.fraseric.ca" in final_url2 and "/user/login" in urlsplit(final_url2).path:
            await self._login_via_learning_sso_requests(final_url2, username, password)
            return

        if final_url2 and (MOODLE_BASE not in final_url2):
            raise RuntimeError(f"Unexpected redirect after Moodle login: {final_url2}")

    async def logout(self) -> None:
        try:
            await self.sess.req.get(MOODLE_LOGOUT_URL)
        except Exception:
            pass

    async def get_full_snapshot(self, username: str, password: str) -> dict:
        """Fetch Moodle overview + per-course grade report and return a JSON-serializable snapshot.

        Snapshot format:
          {
            "fetched_at": "...ISO...",
            "courses": [
              {
                "course_id": 4401,
                "name": "...",
                "url": "...",
                "grade_overview": "...",
                "archived": true,
                "term_label": "FIC 202403",
                "course_code": "CNQS101",
                "items": [ {item fields...}, ... ],
                "error": null | "..."
              },
              ...
            ]
          }
        """
        # Try request-based approach first (fast).
        try:
            await self.login(username, password)

            resp = await self.sess.req.get(MOODLE_OVERVIEW_URL)
            overview_html = await resp.text()

            # Some accounts/pages show the 'not enrolled' notice once, then the table appears on refresh.
            for _ in range(3):
                if not moodle_overview_has_not_enrolled_message(overview_html):
                    break
                await asyncio.sleep(0.8)
                resp = await self.sess.req.get(MOODLE_OVERVIEW_URL)
                overview_html = await resp.text()

            raw_courses = parse_moodle_overview_courses(overview_html)
            courses = self._sanitize_courses(raw_courses)
            snapshot = {"courses": [], "fetched_at": datetime.now(timezone.utc).isoformat()}

            sem = asyncio.Semaphore(6)

            async def fetch_course(course, url: str) -> dict:
                async with sem:
                    try:
                        if not url:
                            raise RuntimeError("Invalid course URL")
                        archived_flag = self._apply_archive_policy(bool(getattr(course, "archived", False)), getattr(course, "term_label", ""), getattr(course, "course_code", ""))
                        r = await self.sess.req.get(url)
                        report_html = await r.text()
                        parsed_items = parse_moodle_course_report(report_html)
                        items_dicts = [item.__dict__ for item in parsed_items]
                        derived_grade = self._derive_overview_grade(course.grade, items_dicts)
                        return {
                            "course_id": course.course_id,
                            "name": course.name,
                            "url": url,
                            "grade_overview": derived_grade,
                            "archived": archived_flag,
                            "term_label": course.term_label,
                            "course_code": course.course_code,
                            "items": items_dicts,
                            "error": None,
                        }
                    except Exception as e:
                        archived_flag = self._apply_archive_policy(bool(getattr(course, "archived", False)), getattr(course, "term_label", ""), getattr(course, "course_code", ""))
                        return {
                            "course_id": course.course_id,
                            "name": course.name,
                            "url": url,
                            "grade_overview": course.grade,
                            "archived": archived_flag,
                            "term_label": course.term_label,
                            "course_code": course.course_code,
                            "items": [],
                            "error": str(e),
                        }

            tasks = [fetch_course(c, c_url) for c, c_url in courses]
            snapshot["courses"] = await asyncio.gather(*tasks)

            await self.logout()
            return snapshot

        except Exception as e:
            msg = str(e)
            if "SAMLRequest" in msg or "SSO login did not complete" in msg or "learning.fraseric.ca" in msg:
                return await self._get_full_snapshot_via_browser(username, password)
            raise


    async def get_overview_grades(self, username: str, password: str) -> Dict[str, Dict[str, str]]:
        # Try request-based approach first (fast).
        try:
            await self.login(username, password)
            resp = await self.sess.req.get(MOODLE_OVERVIEW_URL)
            html = await resp.text()
            for _ in range(3):
                if not moodle_overview_has_not_enrolled_message(html):
                    break
                await asyncio.sleep(0.8)
                resp = await self.sess.req.get(MOODLE_OVERVIEW_URL)
                html = await resp.text()
            data = parse_moodle_overview(html)
            await self.logout()
            return data
        except Exception as e:
            # If it looks like SSO got stuck, retry via headless browser.
            msg = str(e)
            if "SAMLRequest" in msg or "SSO login did not complete" in msg or "learning.fraseric.ca" in msg:
                html = await self._get_overview_html_via_browser(username, password)
                return parse_moodle_overview(html)
            raise
