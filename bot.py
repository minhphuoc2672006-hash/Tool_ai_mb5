from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

from ai_engine import analyze
from ocr import read_image
from money import split_money

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    await file.download_to_drive("img.jpg")

    data = read_image("img.jpg")

    if len(data) < 5:
        await update.message.reply_text("❌ Không đọc được dữ liệu")
        return

    result = analyze(data)

    msg = f"""
🎯 Dự đoán: {result['predict']}
📊 Xác suất: {int(result['confidence']*100)}%
🧠 Phân tích: {result['reason']}
"""

    await update.message.reply_text(msg)


async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = int(context.args[0])
    split = split_money(total)

    msg = "💰 Chia tiền:\n"
    for k, v in split.items():
        msg += f"{k}: {int(v)}\n"

    await update.message.reply_text(msg)


app = ApplicationBuilder().token("YOUR_TOKEN").build()

app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(CommandHandler("money", money))

app.run_polling()
