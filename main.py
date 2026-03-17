import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# ===== AI =====
def analyze(data):
    last = data[-1]

    if last >= 11:
        return {"predict": "TÀI 🔴", "confidence": 0.7, "reason": ">=11"}
    else:
        return {"predict": "XỈU 🔵", "confidence": 0.7, "reason": "<11"}

# ===== FORMAT =====
def format_result(result, history):
    return f"""
🎯 {result['predict']}
📊 {int(result['confidence']*100)}%
📈 {result['reason']}
📉 {" - ".join(map(str, history[-5:]))}
"""

# ===== HANDLE TEXT =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        data = list(map(int, text.split("-")))

        if len(data) < 3:
            await update.message.reply_text("❌ Nhập ít nhất 3 số")
            return

        result = analyze(data)
        await update.message.reply_text(format_result(result, data))

    except:
        await update.message.reply_text("❌ Nhập dạng: 12-13-9-11")

# ===== MONEY =====
async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        total = int(context.args[0])
        each = total // 5
        await update.message.reply_text(f"💰 Chia: {each} x 5 lệnh")
    except:
        await update.message.reply_text("❌ /money 1000")

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot chạy OK rồi!")

# ===== RUN =====
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("money", money))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("🤖 RUNNING...")

app.run_polling()
