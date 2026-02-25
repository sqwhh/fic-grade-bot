"""Quick sanity checks for local setup.

- Ensures .env exists
- Ensures DB_PATH directory is writable
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    env_path = Path(".env")
    if not env_path.exists():
        print("ERROR: .env not found. Copy .env.example -> .env and fill BOT_TOKEN/FERNET_KEY")
        return 1

    db_path = os.getenv("DB_PATH", "./data/bot.db")
    p = Path(db_path)
    try:
        if str(p.parent) not in (".", ""):
            p.parent.mkdir(parents=True, exist_ok=True)
        # touch file (do not overwrite)
        if not p.exists():
            p.touch()
        print(f"OK: DB_PATH is writable: {p}")
    except Exception as e:
        print(f"ERROR: DB_PATH not writable: {db_path} ({e})")
        return 1

    print("OK: basic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
