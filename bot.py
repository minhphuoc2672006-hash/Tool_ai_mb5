import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

from ai_engine import analyze
from ocr import read_image
from money import split_money

TOKEN = os.getenv("TOKEN") or os.getenv("TOKEN_BOT")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

def format_result(result, history):
    bar = "█" * int(result['confidence']*10) + "░" * (10 - int(result['confidence']*10))
    return f"""
🎯 {result['predict']}
📊 {int(result['confidence']*100)}%
[{bar}]
📈 {result['reason']}
📉 {" - ".join(map(str, history[-6:]))}
"""

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    await file.download_to_drive("img.jpg")

    data = read_image("img.jpg")

    if len(data) < 5:
        await update.message.reply_text("❌ Không đọc được")
        return

    result = analyze(data)

    await update.message.reply_text(format_result(result, data))

async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = int(context.args[0])
    split = split_money(total)

    await update.message.reply_text(str(split))

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CommandHandler("money", money))

print("🤖 RUNNING...")

app.run_polling()
