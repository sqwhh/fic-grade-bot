"""Run the bot with: `python -m fic_grade_bot`."""

import asyncio
import logging
import sys

from .app import main


def run() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped manually")


if __name__ == "__main__":
    run()
