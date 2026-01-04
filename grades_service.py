from __future__ import annotations

from typing import Dict

from playwright.async_api import Playwright

from constants import BASE
from session import PortalSession
from fic_portal import FICClient


class GradesService:
    """High-level facade over portal clients.

    This project currently supports only **FIC final grades**.
    """

    def __init__(self, shared_pw: Playwright | None = None):
        self.session = PortalSession(base_url=BASE)
        if shared_pw is not None:
            # Reuse the shared Playwright instance managed by playwright_manager
            self.session.pw = shared_pw
        self.fic = FICClient(self.session)

    async def close(self) -> None:
        await self.session.close()

    async def fic_final_grades(self, username: str, password: str) -> Dict[str, Dict[str, str]]:
        return await self.fic.get_final_grades(username, password)
