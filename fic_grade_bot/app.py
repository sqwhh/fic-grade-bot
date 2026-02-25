"""Telegram bot application entry point."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import BOT_TOKEN
from .db.database import init_db
from .monitoring.monitoring import resume_tasks_on_start, fic_monitor_tasks
from .browser.playwright_manager import stop_playwright
from .telegram.handlers import common, demo, grades, registration, settings


async def main() -> None:
    """Run DB migrations, start routers, and start polling."""
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Routers
    dp.include_router(registration.router)
    dp.include_router(grades.router)
    dp.include_router(settings.router)
    dp.include_router(common.router)
    dp.include_router(demo.router)

    try:
        # Start background monitoring tasks for existing users.
        await resume_tasks_on_start(bot)

        # Start polling.
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
