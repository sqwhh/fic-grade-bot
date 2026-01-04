# FIC final grades telegram bot 📚

A Telegram bot that logs into the **Fraser International College (FIC)** student portal and:

- shows your **final grades** in Telegram
- calculates a **credit‑weighted GPA**
- **monitors** for changes and **notifies** you automatically

> ⚠️ **Disclaimer:** This project is **not affiliated** with Fraser International College / SFU. Use responsibly and at your own risk.

---

## Features

- 🔐 Guided registration (send **login**, then **password**)
- 🔒 Credentials stored **encrypted** (Fernet) in SQLite
- 📚 View cached grades (fast) + manual refresh (~ a few seconds)
- 📊 GPA calculation using a course‑credits map
- 🔔 Background monitoring + change notifications
- ⏳ Notifications auto‑turn off after a configurable number of days
- 🧹 `/delete` wipes your saved data

---

## Commands

- `/start` — start the bot / main menu
- `/mygrades` — open “My Grades”
- `/status` — show last update + last error (if any)
- `/start_monitor` — enable monitoring + notifications
- `/stop` — disable notifications
- `/delete` — delete stored data (credentials, snapshots, settings)

---

## Configuration

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_bot_token_here
FERNET_KEY=your_fernet_key_here

# Optional
CHECK_INTERVAL_SEC=600
NOTIF_DURATION_DAYS=14
NOTIF_WARN_BEFORE_DAYS=1
DB_PATH=bot.db
```

### Generate a Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Run locally

```bash
git clone https://github.com/sqwhh/fic-grade-bot.git
cd fic-grade-bot

python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate  # Windows

pip install -r requirements.txt
python -m playwright install

python bot.py
```

---

## Docker

If you use Docker (recommended for servers):

```bash
docker compose up -d --build
```

Tip: mount a volume for the database so your users/settings persist.  
Set `DB_PATH` to match the mounted location (example: `/data/bot.db`).

---

## How it works (high level)

1. Uses Playwright’s **APIRequestContext** to sign in to the portal.
2. Fetches the **final grades** page and parses the results table.
3. Stores a normalized snapshot + hash in SQLite.
4. A background task checks every `CHECK_INTERVAL_SEC` seconds:
   - if a snapshot changes → sends a Telegram notification

---

## Project structure

- `bot.py` — entry point, dispatcher, startup/shutdown
- `common.py` — `/start`, main menu, basic commands
- `registration.py` — login/password FSM registration flow
- `grades.py` — grades UI, refresh, GPA view
- `messages.py` — formatting, GPA calculation, credits map
- `monitoring.py` — monitoring loop + notifications
- `fic_portal.py` — portal client (login + fetch)
- `fic_results.py` — HTML parsing (results table)
- `database.py` — SQLite storage + helpers
- `keyboards.py` — inline keyboards
- `settings.py` — settings panel + `/delete`
- `config.py` — env loading + constants + Fernet init
- `session.py`, `playwright_manager.py`, `utils.py`, `constants.py` — helpers
