import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# ===== AI CORE =====
def analyze(data):
    if len(data) < 3:
        return {"predict": "❌ Thiếu data", "confidence": 0, "reason": "Không đủ dữ liệu"}

    # tổng 3 số gần nhất
    last = data[-1]
    total = sum(last)

    if total >= 11:
        predict = "TÀI 🔴"
    else:
        predict = "XỈU 🔵"

    confidence = min(0.95, 0.5 + len(data)*0.02)

    return {
        "predict": predict,
        "confidence": confidence,
        "reason": f"Tổng gần nhất = {total}"
    }

# ===== OCR GIẢ =====
def read_image(path):
    # tạm thời fix lỗi import (bạn chưa có OCR thật)
    # trả random data demo
    return [
        (3,4,5),
        (6,6,2),
        (1,2,3),
        (4,5,6),
        (2,2,3)
    ]

# ===== MONEY =====
def split_money(total):
    base = total // 5
    return [base]*5

# ===== FORMAT =====
def format_result(result, history):
    bar = "█" * int(result['confidence']*10) + "░" * (10 - int(result['confidence']*10))
    return f"""
🎯 {result['predict']}
📊 {int(result['confidence']*100)}%
[{bar}]
📈 {result['reason']}
📉 {" | ".join([str(sum(x)) for x in history[-6:]])}
"""

# ===== HANDLER =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    await file.download_to_drive("img.jpg")

    data = read_image("img.jpg")

    result = analyze(data)

    await update.message.reply_text(format_result(result, data))


async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Nhập số tiền. VD: /money 1000")
        return

    total = int(context.args[0])
    split = split_money(total)

    await update.message.reply_text(f"💰 Chia tiền: {split}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot AI Tài Xỉu đang chạy!")


# ===== MAIN =====
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("money", money))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

print("🤖 RUNNING...")

app.run_polling()
