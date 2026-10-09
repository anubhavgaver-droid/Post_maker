import os

API_ID = int(os.environ.get("API_ID", "1234567"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")

# Admins list
ADMINS_RAW = os.environ.get("ADMIN_IDS", "5898522531,6225923811")
ADMIN_IDS = [int(x.strip()) for x in ADMINS_RAW.split(",") if x.strip()]

# Web Server Configuration for Render
PORT = int(os.environ.get("PORT", "8080"))
PING_INTERVAL = 240  # Self ping every 4 minutes (240 seconds)
