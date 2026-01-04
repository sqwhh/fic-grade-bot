# bot.py
"""Telegram bot entry point.

This project uses a **flat module layout** (no `services.*` / `handlers.*`
packages) to make Docker deployment and imports straightforward.

Included:
- FIC final grades monitoring + notifications
- Manual grades view + GPA calculation

Removed:
- Moodle grade checker
- Enrollment checker
"""

import asyncio
import logging
import sys

# Playwright may emit TargetClosedError during Ctrl+C shutdown.
try:
    from playwright._impl._errors import TargetClosedError  # type: ignore
except Exception:  # pragma: no cover
    TargetClosedError = None  # type: ignore

try:
    from playwright.async_api import Error as PlaywrightError
except Exception:  # pragma: no cover
    PlaywrightError = Exception  # type: ignore

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db
from monitoring import resume_tasks_on_start, fic_monitor_tasks
from playwright_manager import stop_playwright

import common
import registration
import grades
import settings


async def main() -> None:
    """Application entry point."""
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # --- Suppress the noisy asyncio log emitted by Future.__del__ during Playwright shutdown.
    # That message bypasses the loop exception handler and is harmless in our Ctrl+C shutdown path.
    class _SuppressAsyncioPlaywrightShutdown(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.name != "asyncio":
                return True
            msg = record.getMessage()
            if "Future exception was never retrieved" not in msg:
                return True
            exc = None
            if record.exc_info and len(record.exc_info) >= 2:
                exc = record.exc_info[1]
            if exc is None:
                return True
            s = str(exc)
            if "Target page, context or browser has been closed" in s:
                return False
            return True

    logging.getLogger("asyncio").addFilter(_SuppressAsyncioPlaywrightShutdown())

    # Suppress noisy Playwright shutdown errors (Ctrl+C).
    loop = asyncio.get_running_loop()

    def _loop_exc_handler(loop, context):
        exc = context.get('exception')
        if exc is not None:
            if TargetClosedError is not None and isinstance(exc, TargetClosedError):
                return
            # Fallback: match by message (Playwright's error types vary by version)
            if isinstance(exc, PlaywrightError) and 'Target page, context or browser has been closed' in str(exc):
                return
        loop.default_exception_handler(context)

    loop.set_exception_handler(_loop_exc_handler)

    # Routers
    dp.include_router(registration.router)
    dp.include_router(grades.router)
    dp.include_router(settings.router)
    dp.include_router(common.router)

    try:
        # Start background monitoring tasks for existing users
        await resume_tasks_on_start(bot)

        # Start polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        logging.info("Shutting down…")
        tasks = list(fic_monitor_tasks.values())
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await stop_playwright()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass
        logging.info("Shutdown complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped manually")
