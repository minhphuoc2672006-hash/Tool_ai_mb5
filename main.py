import os
import asyncio
import random
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ===== CONFIG =====
TOKEN = os.getenv("TOKEN")  # 🔒 ẨN TOKEN
if not TOKEN:
    raise Exception("❌ Thiếu TOKEN ENV")

users = {}

# ===== LOGIC =====
def get_tx(history):
    return ["Tài" if sum(x) >= 11 else "Xỉu" for x in history]

def markov(tx):
    if len(tx) < 2:
        return None, 0
    t = {"Tài": {"Tài": 0, "Xỉu": 0},
         "Xỉu": {"Tài": 0, "Xỉu": 0}}
    for i in range(len(tx)-1):
        t[tx[i]][tx[i+1]] += 1
    last = tx[-1]
    if t[last]["Tài"] > t[last]["Xỉu"]:
        return "Tài", 0.6
    else:
        return "Xỉu", 0.6

def detect_break(tx):
    if len(tx) < 5:
        return False
    return tx[-5:].count(tx[-1]) == 5

def ai(user):
    tx = get_tx(user["history"])
    pred, conf = markov(tx)
    if pred is None:
        return None, 0
    if detect_break(tx):
        pred = "Xỉu" if tx[-1] == "Tài" else "Tài"
    return pred, conf

# ===== AUTO LẤY LỊCH SỬ (TEST) =====
async def fetch_history():
    # ⚠️ HIỆN TẠI: giả lập để đảm bảo bot chạy 100%
    data = []
    for _ in range(30):
        if random.random() > 0.5:
            data.append([6,6,6])
        else:
            data.append([1,1,1])
    return data

# ===== AUTO LOOP =====
async def auto_run(app):
    while True:
        try:
            history = await fetch_history()

            for uid, user in users.items():
                if len(history) > len(user["history"]):
                    user["history"] = history[-50:]

                    pred, conf = ai(user)
                    if pred:
                        await app.bot.send_message(
                            chat_id=uid,
                            text=f"🤖 KÈO: {pred} ({conf*100:.0f}%)"
                        )

        except Exception as e:
            print("Lỗi:", e)

        await asyncio.sleep(10)

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    users[uid] = {"history": []}
    await update.message.reply_text("✅ Bot đã chạy auto!")

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # chạy auto nền
    app.job_queue.run_once(
        lambda ctx: asyncio.create_task(auto_run(app)), 1
    )

    print("🔥 BOT RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
