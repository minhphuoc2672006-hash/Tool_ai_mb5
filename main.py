import os
import asyncio
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise Exception("❌ Thiếu TOKEN")

users = {}

# ===== CHUYỂN TÀI/XỈU =====
def get_tx(history):
    return ["Tài" if sum(x) >= 11 else "Xỉu" for x in history]

# ===== MARKOV AI =====
def markov(tx):
    if len(tx) < 2:
        return None, 0

    trans = {
        "Tài": {"Tài": 0, "Xỉu": 0},
        "Xỉu": {"Tài": 0, "Xỉu": 0}
    }

    for i in range(len(tx) - 1):
        trans[tx[i]][tx[i+1]] += 1

    last = tx[-1]

    if trans[last]["Tài"] > trans[last]["Xỉu"]:
        return "Tài", 0.65
    else:
        return "Xỉu", 0.65

# ===== PHÁT HIỆN CẦU GÃY =====
def detect_break(tx):
    if len(tx) < 5:
        return False

    last5 = tx[-5:]
    return last5.count(last5[0]) == 5

# ===== AI TỔNG =====
def ai(user):
    tx = get_tx(user["history"])

    pred, conf = markov(tx)

    if pred is None:
        return None, 0

    # nếu cầu bệt → đảo
    if detect_break(tx):
        pred = "Xỉu" if tx[-1] == "Tài" else "Tài"

    return pred, conf

# ===== LẤY LỊCH SỬ (GIẢ LẬP + ỔN ĐỊNH) =====
# 👉 Sau này thay bằng Playwright/API
import random
async def fetch_history():
    data = []
    for _ in range(30):
        if random.random() > 0.5:
            data.append([6,6,6])
        else:
            data.append([1,1,1])
    return data

# ===== AUTO =====
async def auto_run(app):
    while True:
        try:
            history = await fetch_history()

            for uid, user in users.items():

                # nếu có ván mới
                if len(history) > len(user["history"]):

                    user["history"] = history[-50:]

                    pred, conf = ai(user)

                    if pred:
                        await app.bot.send_message(
                            chat_id=uid,
                            text=f"⏳ KÈO SỚM (trước ~40s)\n🎯 {pred}\n📊 {conf*100:.0f}%"
                        )

        except Exception as e:
            print("Lỗi:", e)

        await asyncio.sleep(5)

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    users[uid] = {
        "history": []
    }

    await update.message.reply_text("🤖 Bot AI đã bật!")

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # 🔥 chạy nền KHÔNG lỗi
    async def startup(app):
        asyncio.create_task(auto_run(app))

    app.post_init = startup

    print("🔥 BOT RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
