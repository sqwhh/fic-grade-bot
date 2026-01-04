# fic-grade-bot 🤖📚

A Telegram bot that logs into **Fraser International College (FIC)** portal (**learning.fraseric.ca**) and:

- shows your **final grades** inside Telegram
- calculates a **GPA** (based on stored course credits)
- **monitors** your grades in the background and **notifies you** when something changes

> ⚠️ **Disclaimer:** This project is **not affiliated** with Fraser International College / SFU. Use it responsibly and at your own risk.

---

## Features

- 🔐 **Registration flow** (user sends login → password)
- 🧠 Credentials stored **encrypted** (Fernet)
- 📗 View **FIC final grades**
- 📊 **GPA calculation** (credit-weighted)
- 🔔 Background **monitoring + notifications**
- ⏳ Notifications **auto-disable** after a configurable number of days
- 🧹 `/delete` wipes your data & turns notifications off

---

## Bot commands

- `/start` — start the bot / show main menu
- `/mygrades` — open grades menu (FIC grades)
- `/status` — show last update / last error info
- `/start_monitor` — enable monitoring (FIC)
- `/stop` — disable monitoring (FIC)
- `/delete` — delete your saved data and credentials

Most actions are also available via inline buttons in the bot UI.

---

## Tech stack

- **Python**
- **aiogram** (Telegram bot framework)
- **Playwright** (uses APIRequestContext to talk to the portal)
- **SQLite** (via aiosqlite)
- **cryptography (Fernet)** for credential encryption
- **BeautifulSoup** for parsing the results table
- **python-dotenv** for `.env` config

---

## Project structure (flat layout)

- `bot.py` — entry point, dispatcher setup, graceful shutdown
- `common.py` — `/start`, main menu, status/monitor commands
- `registration.py` — login/password registration FSM
- `grades.py` — “My Grades”, GPA view, refresh logic
- `settings.py` — settings panel, notifications toggle, `/delete`
- `monitoring.py` — background loop that checks grades & sends notifications
- `grades_service.py` — high-level service wrapper
- `fic_portal.py` — FIC client: login + fetch final grades
- `fic_results.py` — HTML parser for the “Results” table
- `database.py` — SQLite schema + storage (encrypted creds, snapshots, state)
- `messages.py` — message builders + GPA + course credits map
- `keyboards.py` — inline keyboards (menus/buttons)
- `config.py` — env loading + config values + Fernet initialization
- `constants.py` — portal URLs
- `utils.py` — helpers (hashing, safe edits, formatting, error mapping)
- `playwright_manager.py` — shared Playwright instance manager
- `session.py` — Playwright request context wrapper

---

## Setup (local)

### 1) Clone

```bash
git clone https://github.com/sqwhh/fic-grade-bot.git
cd fic-grade-bot
