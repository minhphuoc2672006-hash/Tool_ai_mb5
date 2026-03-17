import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ===== LOG =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ===== TOKEN (ẨN) =====
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("❌ Chưa set TOKEN")

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot đang chạy OK!")

# ===== XỬ LÝ TEXT =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()

        # nhập dạng: 3-4-5
        nums = list(map(int, text.split("-")))

        if len(nums) < 3:
            await update.message.reply_text("❌ Nhập ít nhất 3 số (vd: 3-4-5)")
            return

        total = sum(nums)

        if total >= 11:
            result = "TÀI 🔴"
        else:
            result = "XỈU 🔵"

        await update.message.reply_text(
            f"🎯 {result}\n📊 Tổng: {total}"
        )

    except:
        await update.message.reply_text("❌ Sai định dạng (vd: 3-4-5)")

# ===== MONEY =====
async def money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        total = int(context.args[0])
        each = total // 5
        await update.message.reply_text(f"💰 Chia: {each} x 5 lệnh")
    except:
        await update.message.reply_text("❌ /money 1000")

# ===== MAIN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("money", money))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

print("🤖 BOT RUNNING...")

app.run_polling()
