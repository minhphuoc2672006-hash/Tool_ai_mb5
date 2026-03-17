import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

from ai_engine import analyze
from ocr import read_image
from money import split_money

# ===== TOKEN (ẨN) =====
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN môi trường")

# ===== UI RESULT =====
def format_result(result, history):
    bar = "█" * int(result['confidence']*10) + "░" * (10 - int(result['confidence']*10))

    return f"""
🎯 <b>DỰ ĐOÁN:</b> {result['predict']}

📊 <b>XÁC SUẤT:</b> {int(result['confidence']*100)}%
[{bar}]

📈 <b>PHÂN TÍCH:</b>
{result['reason']}

📉 <b>CHUỖI:</b>
{" - ".join(map(str, history[-6:]))}

━━━━━━━━━━━━━━
🤖 AI TX PRO
"""

# ===== UI MONEY =====
def format_money(split):
    return f"""
💰 <b>CHIẾN LƯỢC VỐN</b>

🎯 Lệnh 1: {split['Lệnh 1 (chính)']}
🎯 Lệnh 2: {split['Lệnh 2']}
🎯 Lệnh 3: {split['Lệnh 3']}
🎯 Lệnh 4: {split['Lệnh 4']}

🛡 Dự phòng: {split['Dự phòng']}

━━━━━━━━━━━━━━
⚠️ Thua 2 nghỉ - Thắng 1 chốt
"""

# ===== HANDLE ẢNH =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.photo[-1].get_file()
        await file.download_to_drive("img.jpg")

        data = read_image("img.jpg")

        if len(data) < 5:
            await update.message.reply_text("❌ Không đọc được dữ liệu")
            return

        result = analyze(data)

        await update.message.reply_text(
            format_result(result, data),
            parse_mode="HTML"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")

# ===== COMMAND MONEY =====
async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("❌ Nhập số tiền. VD: /money 50000")
            return

        total = int(context.args[0])
        split = split_money(total)

        await update.message.reply_text(
            format_money(split),
            parse_mode="HTML"
        )

    except:
        await update.message.reply_text("❌ Lỗi nhập tiền")

# ===== RUN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CommandHandler("money", money))

print("🤖 Bot đang chạy...")

app.run_polling()
