# config.py
import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
FERNET_KEY = os.getenv("FERNET_KEY")

# How often to check grades (seconds)
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "600"))

# Notifications auto-off window (days).
# When a user enables grade notifications, they stay enabled only for this duration
# and then turn off automatically.
NOTIF_DURATION_DAYS = int(os.getenv("NOTIF_DURATION_DAYS", "14"))

# How long before auto-off to send a warning message (days).
NOTIF_WARN_BEFORE_DAYS = int(os.getenv("NOTIF_WARN_BEFORE_DAYS", "1"))

# SQLite DB path (inside Docker you can map it to /data/bot.db via volume)
DB_PATH = os.getenv("DB_PATH", "bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not FERNET_KEY:
    raise RuntimeError("FERNET_KEY is not set")

fernet = Fernet(FERNET_KEY)
