import os
import logging
import asyncio
import random
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise Exception("❌ Thiếu TOKEN")

users = {}

STRATEGIES = ["FOLLOW","OPPOSITE","TREND","RANDOM"]

# ===== BASIC =====
def money(x):
    return f"{int(x):,}".replace(",", ".")

def classify(total):
    return "Tài" if total >= 11 else "Xỉu"

def get_tx(history):
    return ["Tài" if sum(x)>=11 else "Xỉu" for x in history]

# ===== STRATEGY =====
def run_strategy(name, history):
    tx = get_tx(history)

    if name == "FOLLOW":
        return tx[-1] if tx else random.choice(["Tài","Xỉu"])

    if name == "OPPOSITE":
        return "Xỉu" if tx and tx[-1]=="Tài" else "Tài"

    if name == "TREND":
        if len(tx)>=4:
            return "Tài" if tx[-4:].count("Tài") > tx[-4:].count("Xỉu") else "Xỉu"

    return random.choice(["Tài","Xỉu"])

# ===== CHỌN CHIẾN THUẬT =====
def pick_strategy():
    return random.choice(STRATEGIES)

# ===== AI =====
def ai_predict(user):
    pred = run_strategy(user["strategy"], user["history"])
    return pred, 0.6

# ===== BET =====
def bet_calc(user):
    base = user["money"] * 0.05

    if user["lose"] == 0:
        return int(base)

    return int(min(base * (2 ** user["lose"]), user["money"] * 0.3))

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 AI TÀI XỈU\n/setmoney 500000")

async def setmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    m = int(context.args[0])

    users[uid] = {
        "money": m,
        "start": m,
        "profit": 0,
        "win": 0,
        "lose": 0,
        "last_pred": None,
        "last_bet": 0,
        "history": [],
        "strategy": pick_strategy()
    }

    await update.message.reply_text(f"💰 Vốn: {money(m)}")

# ===== MAIN =====
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    if uid not in users:
        await update.message.reply_text("❗ /setmoney trước")
        return

    user = users[uid]

    nums = [int(x) for x in text.replace("-", " ").split() if x.isdigit()]
    if len(nums) != 3:
        await update.message.reply_text("❗ Nhập: 3-5-6")
        return

    dice = nums
    real = classify(sum(dice))

    msg_wait = await update.message.reply_text("⏳ Đang phân tích...")
    await asyncio.sleep(0.5)

    user["history"].append(dice)
    if len(user["history"]) > 30:
        user["history"].pop(0)

    result = ""
    last_bet = user["last_bet"]

    # ===== CHECK WIN/LOSE =====
    if user["last_pred"] is not None:
        if user["last_pred"] == real:
            user["money"] += last_bet
            user["profit"] += last_bet
            user["win"] += 1
            user["lose"] = 0
            result = f"✅ WIN (+{money(last_bet)})"
        else:
            user["money"] -= last_bet
            user["profit"] -= last_bet
            user["lose"] += 1
            result = f"❌ LOSE (-{money(last_bet)})"

            # 🔥 THUA 1 → ĐỔI NGAY CHIẾN THUẬT
            user["strategy"] = pick_strategy()

    # ===== PREDICT NGAY SAU KHI ĐỔI =====
    pred, conf = ai_predict(user)
    next_bet = bet_calc(user)

    user["last_pred"] = pred
    user["last_bet"] = next_bet

    # ===== UI GỌN =====
    msg = (
        f"🎲 {dice} → {real}\n"
        f"{result}\n"
        "────────────\n"
        f"🤖 Dự đoán: {pred}\n"
        f"💰 Cược trước: {money(last_bet)}\n"
        f"💸 Cược tiếp: {money(next_bet)}\n"
        f"📊 Vốn: {money(user['money'])}\n"
        f"📈 Lãi: {money(user['profit'])}\n"
        f"🧠 Chiến thuật: {user['strategy']}\n"
        f"🏆 {user['win']} | ❌ {user['lose']}"
    )

    await msg_wait.edit_text(msg)

# ===== RUN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmoney", setmoney))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("🔥 BOT RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
