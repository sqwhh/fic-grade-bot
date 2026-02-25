from __future__ import annotations

from typing import Dict

from playwright.async_api import Playwright

from ..browser.session import PortalSession
from ..constants import BASE, MOODLE_BASE
from ..portals.fic_portal import FICClient
from ..portals.moodle_portal import MoodleClient


class GradesService:
    """High-level facade over portal clients."""

    def __init__(self, shared_pw: Playwright | None = None):
        self.fic_session = PortalSession(base_url=BASE)
        self.moodle_session = PortalSession(base_url=MOODLE_BASE)

        if shared_pw is not None:
            # Reuse the shared Playwright instance managed by playwright_manager.
            self.fic_session.pw = shared_pw
            self.moodle_session.pw = shared_pw

        self.fic = FICClient(self.fic_session)
        self.moodle = MoodleClient(self.moodle_session)

    async def close(self) -> None:
        await self.fic_session.close()
        await self.moodle_session.close()

    async def fic_final_grades(self, username: str, password: str) -> Dict[str, Dict[str, str]]:
        return await self.fic.get_final_grades(username, password)

    async def moodle_overview_grades(self, username: str, password: str) -> Dict[str, Dict[str, str]]:
        return await self.moodle.get_overview_grades(username, password)

    async def moodle_full_snapshot(self, username: str, password: str) -> dict:
        return await self.moodle.get_full_snapshot(username, password)
