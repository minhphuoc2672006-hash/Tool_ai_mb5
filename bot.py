import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

last_result = "Chưa có dữ liệu"

def set_result(data):
    global last_result
    last_result = data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 TOOL AI MB5 ONLINE")

async def kq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_result
    await update.message.reply_text(f"📊 {last_result}")

def run_bot():
    print("🤖 Starting telegram bot...")

    if not BOT_TOKEN:
        raise Exception("❌ BOT_TOKEN chưa set trên Railway")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kq", kq))

    app.run_polling()
