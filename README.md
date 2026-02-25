# FIC + Moodle grades Telegram bot 📚

A Telegram bot that logs into the **Fraser International College (FIC)** portals and:

- shows your **final FIC grades**
- shows your **Moodle grade overview**
- calculates a **credit‑weighted GPA** (based on FIC final grades)
- **monitors** for changes and **notifies** you automatically

> ⚠️ Disclaimer: this project is **not affiliated** with Fraser International College / SFU. Use responsibly.

---

## Features

- 🔐 Guided registration (send **login**, then **password**)
- 🔒 Credentials stored **encrypted** (Fernet) in SQLite
- 📗 FIC final grades: cached view + manual refresh
- 📙 Moodle grades: cached view + manual refresh
- 📊 GPA calculation (credit‑weighted)
- 🔔 Background monitoring + change notifications
- ⏳ Notifications auto‑turn off after a configurable number of days
- 🧪 Demo profile that showcases UI + notifications (simulated)

---

## Commands

- `/start` — start / main menu
- `/mygrades` — open “My Grades” (FIC + Moodle)
- `/moodle` — open “Moodle grades” directly
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
MOODLE_CHECK_INTERVAL_SEC=900
NOTIF_DURATION_DAYS=14
MOODLE_NOTIF_DURATION_DAYS=60
MOODLE_NOTIF_MAX_DAYS=60
NOTIF_WARN_BEFORE_DAYS=1
MOODLE_NOTIF_WARN_BEFORE_DAYS=1
DB_PATH=./data/bot.db
```

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\\Scripts\\activate  # Windows

pip install -r requirements.txt
python -m playwright install chromium

python -m fic_grade_bot
# or: python bot.py
```

---

## Docker

```bash
docker compose up -d --build
```

Tip: mount a volume for the database so your users/settings persist.

---

## Project structure

```
.
├── bot.py                      # backward-compatible entry point
├── fic_grade_bot/              # Python package
│   ├── app.py                  # bot startup/shutdown
│   ├── config.py               # env + Fernet
│   ├── constants.py            # URLs
│   ├── utils.py                # helpers
│   ├── browser/                # Playwright shared instance + request context
│   ├── db/                     # SQLite layer
│   ├── portals/                # FIC/Moodle clients
│   ├── parsers/                # HTML parsers
│   ├── services/               # high-level facade (GradesService)
│   ├── monitoring/             # background monitoring loop
│   └── telegram/               # UI: keyboards, messages, handlers
│       └── handlers/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── data/                       # local DB folder (gitignored)
```

## Quick links

- Local setup: `docs/LOCAL_SETUP.md`
- Push to GitHub branch: `docs/PUSH_TO_GITHUB_BRANCH.md`
- Example env file: `.env.example`
