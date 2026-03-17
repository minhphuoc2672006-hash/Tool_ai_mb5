import os
import requests
from telegram.ext import Updater, CommandHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


# =========================
# SEND MESSAGE
# =========================

def send(msg):

    if not BOT_TOKEN or not CHAT_ID:
        print("Missing telegram config")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Telegram error:", e)


# =========================
# COMMANDS
# =========================

def start(update, context):
    update.message.reply_text("🤖 TOOL MB5 ONLINE")


def status(update, context):
    update.message.reply_text("✅ BOT RUNNING")


# =========================
# RUN BOT
# =========================

def run_bot():

    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return

    updater = Updater(BOT_TOKEN)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("status", status))

    updater.start_polling()

    print("Telegram bot started")

    updater.idle()
