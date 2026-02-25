# config.py
import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")

# How often to check grades (seconds)
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "600"))

# How often to check Moodle grades (seconds).
# Defaults to CHECK_INTERVAL_SEC if not provided.
MOODLE_CHECK_INTERVAL_SEC = int(os.getenv("MOODLE_CHECK_INTERVAL_SEC", str(CHECK_INTERVAL_SEC)))

# Notifications auto-off window (days).
# When a user enables grade notifications, they stay enabled only for this duration
# and then turn off automatically.
NOTIF_DURATION_DAYS = int(os.getenv("NOTIF_DURATION_DAYS", "14"))

# Moodle notifications default duration (days).
# This is independent from FIC notifications.
MOODLE_NOTIF_DURATION_DAYS = int(os.getenv("MOODLE_NOTIF_DURATION_DAYS", "60"))

# Moodle notifications hard cap (days). By default equals MOODLE_NOTIF_DURATION_DAYS.
MOODLE_NOTIF_MAX_DAYS = int(os.getenv("MOODLE_NOTIF_MAX_DAYS", str(MOODLE_NOTIF_DURATION_DAYS)))

# How long before Moodle auto-off to send a warning message (days).
# Default: 1 day.
MOODLE_NOTIF_WARN_BEFORE_DAYS = int(os.getenv("MOODLE_NOTIF_WARN_BEFORE_DAYS", "1"))

# Moodle courses "Active" policy.
# Moodle overview sometimes lists old courses as not archived. To keep the UI intuitive,
# the bot will treat only the most recent FIC term(s) as "Active" and move the rest to "Archived".
# Default: 1 (current FIC term only).
MOODLE_ACTIVE_TERMS = int(os.getenv("MOODLE_ACTIVE_TERMS", "1"))
if MOODLE_ACTIVE_TERMS < 1:
    MOODLE_ACTIVE_TERMS = 1
if MOODLE_ACTIVE_TERMS > 6:
    MOODLE_ACTIVE_TERMS = 6

# How long before auto-off to send a warning message (days).
NOTIF_WARN_BEFORE_DAYS = int(os.getenv("NOTIF_WARN_BEFORE_DAYS", "1"))

# SQLite DB path (inside Docker you can map it to /data/bot.db via volume)
DB_PATH = os.getenv("DB_PATH", "bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not FERNET_KEY:
    raise RuntimeError("FERNET_KEY is not set")

fernet = Fernet(FERNET_KEY)
