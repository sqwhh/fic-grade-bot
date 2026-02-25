from __future__ import annotations

from typing import Dict, Optional
from urllib.parse import urlsplit, parse_qs

from bs4 import BeautifulSoup

from ..browser.session import PortalSession
from ..constants import BASE, GRADES_URL, LOGIN_URL, LOGOUT_URL, PROFILE_URL
from ..parsers.fic_results import parse_results


class FICClient:
    """Client for learning.fraseric.ca."""

    def __init__(self, session: PortalSession):
        self.sess = session

    async def login(self, username: str, password: str) -> None:
        """Login using the standard FIC login form."""
        await self.sess.start()

        r = await self.sess.req.post(
            LOGIN_URL,
            form={"username": username, "password": password, "x": "27", "y": "4"},
        )

        final_url = (r.url or "").rstrip("/")
        base_url = BASE.rstrip("/")

        if final_url == base_url:
            return

        parts = urlsplit(final_url)
        if parts.path == "/user/login":
            q = parse_qs(parts.query)
            if q.get("username", [""])[0] == username:
                raise ValueError("Invalid username or password.")

        if not r.ok:
            body = await r.text()
            snippet = body[:300].replace("\n", " ")
            raise RuntimeError(f"Login failed: {r.status}. {snippet}...")

        raise RuntimeError(f"Unexpected redirect after login: {r.url}")

    async def logout(self) -> None:
        try:
            await self.sess.req.get(LOGOUT_URL)
        except Exception:
            pass

    @staticmethod
    def _parse_profile_name(html: str) -> Optional[str]:
        """Extract student's full name from the Student Profile HTML."""
        soup = BeautifulSoup(html or "", "html.parser")

        # Most stable: "You are logged in as <strong>NAME (ID)</strong>"
        strong = soup.select_one("#user-box strong")
        if strong:
            txt = strong.get_text(" ", strip=True)
            if txt:
                name = txt.split("(")[0].strip()
                if name:
                    return name

        # Fallback: the "Name:" row in the profile table
        th = soup.find("th", string=lambda s: isinstance(s, str) and s.strip() == "Name:")
        if th:
            td = th.find_next("td")
            if td:
                name = td.get_text(" ", strip=True)
                return name or None

        return None

    async def get_profile_name(self, username: str, password: str) -> Optional[str]:
        """Login, fetch profile page, parse full name, logout."""
        await self.login(username, password)
        try:
            return await self.fetch_profile_name()
        finally:
            await self.logout()

    async def fetch_profile_name(self) -> Optional[str]:
        """Fetch profile page and parse full name (assumes session is logged in)."""
        resp = await self.sess.req.get(PROFILE_URL)
        html = await resp.text()
        return self._parse_profile_name(html)

    async def get_final_grades(self, username: str, password: str) -> Dict[str, Dict[str, str]]:
        await self.login(username, password)
        resp = await self.sess.req.get(GRADES_URL)
        html = await resp.text()
        data = parse_results(html)
        await self.logout()
        return data
