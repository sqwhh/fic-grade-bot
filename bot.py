# bot.py
"""Telegram bot entry point.

This project uses a **flat module layout** (no `services.*` / `handlers.*`
packages) to make Docker deployment and imports straightforward.
"""

import asyncio
import logging
import sys

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
