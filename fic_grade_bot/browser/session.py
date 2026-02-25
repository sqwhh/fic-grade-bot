from __future__ import annotations

from playwright.async_api import Playwright, Error as PlaywrightError

from .playwright_manager import get_playwright_instance


class PortalSession:
    """A single Playwright request context shared by portal clients.

    - `pw` can be injected (shared instance) to avoid repeated start/stop.
    - `req` is a Playwright APIRequestContext.
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.pw: Playwright | None = None
        self.req = None

    async def start(self) -> None:
        if self.pw is None:
            self.pw = await get_playwright_instance()
        if self.req is None:
            self.req = await self.pw.request.new_context(base_url=self.base_url)

    async def close(self) -> None:
        if self.req is not None:
            try:
                await self.req.dispose()
            except PlaywrightError:
                # Happens during shutdown when Playwright was already stopped.
                pass
            except Exception:
                pass
            self.req = None
