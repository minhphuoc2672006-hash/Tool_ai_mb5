import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

from ai_engine import analyze
from ocr import read_image
from money import split_money

TOKEN = os.getenv("TOKEN") or os.getenv("TOKEN_BOT")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

# ===== UI =====
def format_result(result, history):
    try:
        bar = "█" * int(result['confidence']*10) + "░" * (10 - int(result['confidence']*10))

        return f"""
╔══════════════╗
 🤖 AI TX MAX
╚══════════════╝

🎯 Dự đoán: {result['predict']}

📊 Xác suất: {int(result['confidence']*100)}%
[{bar}]

📈 Phân tích:
{result['reason']}

📉 6 ván gần:
{" - ".join(map(str, history[-6:]))}

⚠️ Gợi ý:
• Thua 2 nghỉ
• Thắng 1 chốt
"""
    except:
        return "❌ Lỗi format"

# ===== HANDLE ẢNH =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await update.message.photo[-1].get_file()
        path = "img.jpg"
        await file.download_to_drive(path)

        data = read_image(path)

        if not data or len(data) < 5:
            await update.message.reply_text("❌ Không đọc được dữ liệu")
            return

        result = analyze(data)

        await update.message.reply_text(format_result(result, data))

    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi xử lý ảnh:\n{e}")

# ===== MONEY =====
async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("⚠️ Dùng: /money 50000")
            return

        total = int(context.args[0])
        split = split_money(total)

        msg = "\n".join([f"{k}: {v}" for k, v in split.items()])

        await update.message.reply_text(f"💰 CHIA VỐN\n\n{msg}")

    except:
        await update.message.reply_text("❌ Nhập sai số tiền")

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot AI TX MAX đã sẵn sàng!")

# ===== RUN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("money", money))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

print("🤖 RUNNING...")

app.run_polling()
