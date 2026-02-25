# services/playwright_manager.py
import asyncio

from playwright.async_api import async_playwright, Playwright, Error as PlaywrightError

# Some Playwright shutdown errors come from internal exception classes.
try:
    from playwright._impl._errors import TargetClosedError  # type: ignore
except Exception:  # pragma: no cover
    TargetClosedError = None  # type: ignore

SHARED_PW: Playwright | None = None
SHARED_PW_LOCK = asyncio.Lock()

async def ensure_shared_pw():
    """Ensures the shared Playwright instance is started, using a lock to prevent race conditions."""
    global SHARED_PW
    if SHARED_PW is None:
        async with SHARED_PW_LOCK:
            if SHARED_PW is None:
                SHARED_PW = await async_playwright().start()

async def get_playwright_instance() -> Playwright:
    """Returns the shared Playwright instance, ensuring it's started first."""
    await ensure_shared_pw()
    return SHARED_PW

async def stop_playwright():
    """Stops the shared Playwright instance if it's running."""
    global SHARED_PW
    if SHARED_PW is not None:
        try:
            await SHARED_PW.stop()
        except PlaywrightError:
            # On shutdown, Playwright may already be closed.
            pass
        except Exception as e:
            # TargetClosedError can leak through depending on version.
            if TargetClosedError is not None and isinstance(e, TargetClosedError):
                pass
            else:
                pass
        SHARED_PW = None