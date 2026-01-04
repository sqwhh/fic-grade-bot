from __future__ import annotations

from typing import Dict
from urllib.parse import urlsplit, parse_qs

from constants import BASE, LOGIN_URL, LOGOUT_URL, GRADES_URL
from session import PortalSession
from fic_results import parse_results


class FICClient:
    """Client for learning.fraseric.ca.

    Supports:
    - login/logout
    - fetching final grades
    """

    def __init__(self, session: PortalSession):
        self.sess = session

    async def login(self, username: str, password: str) -> None:
        """Login using the standard FIC login form.

        Notes:
        - On success, FIC typically redirects to BASE (/).
        - On invalid creds, it redirects back to /user/login with query params.
        """
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

    async def get_final_grades(self, username: str, password: str) -> Dict[str, Dict[str, str]]:
        await self.login(username, password)
        resp = await self.sess.req.get(GRADES_URL)
        html = await resp.text()
        data = parse_results(html)
        await self.logout()
        return data
