import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

from ai_engine import analyze
from ocr import read_image
from money import split_money

TOKEN = os.getenv("TOKEN") or os.getenv("TOKEN_BOT")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

# ===== FORMAT =====
def format_result(result, history):
    try:
        bar = "█" * int(result['confidence']*10) + "░" * (10 - int(result['confidence']*10))
        return f"""
🎯 {result['predict']}
📊 {int(result['confidence']*100)}%
[{bar}]
📈 {result['reason']}
📉 {" - ".join(map(str, history[-6:]))}
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

# ===== COMMAND MONEY =====
async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("⚠️ Dùng: /money 100000")
            return

        total = int(context.args[0])
        split = split_money(total)

        await update.message.reply_text(str(split))

    except:
        await update.message.reply_text("❌ Nhập sai số tiền")

# ===== APP =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CommandHandler("money", money))

print("🤖 RUNNING...")

app.run_polling()
