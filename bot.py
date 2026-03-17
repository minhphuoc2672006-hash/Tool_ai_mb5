import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters
)

from ai_engine import analyze
from money import split_money

TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

# ===== FORMAT =====
def format_result(result, history):
    bar = "█" * int(result['confidence'] * 10) + "░" * (10 - int(result['confidence'] * 10))
    return f"""
🎯 {result['predict']}
📊 {int(result['confidence']*100)}%
[{bar}]
📈 {result['reason']}
📉 {" - ".join(map(str, history[-6:]))}
"""

# ===== HANDLE TEXT =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        data = list(map(int, text.split("-")))

        if len(data) < 5:
            await update.message.reply_text("❌ Nhập ít nhất 5 kết quả")
            return

        result = analyze(data)

        await update.message.reply_text(format_result(result, data))

    except:
        await update.message.reply_text("❌ Nhập dạng: 12-13-9-11-14")

# ===== MONEY =====
async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        total = int(context.args[0])
        split = split_money(total)
        await update.message.reply_text(str(split))
    except:
        await update.message.reply_text("❌ Dùng: /money 1000")

# ===== MAIN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(CommandHandler("money", money))

print("🤖 BOT RUNNING...")

app.run_polling()
