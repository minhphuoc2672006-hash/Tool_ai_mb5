import os
import logging
import asyncio
import random
from collections import defaultdict
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

def money(x):
    return f"{int(x):,}".replace(",", ".")

def classify_total(total):
    return "Tài" if total >= 11 else "Xỉu"

def get_tx_history(history):
    return [classify_total(sum(x)) for x in history]

def build_markov(history):
    mapping = defaultdict(lambda: {"Tài": 0, "Xỉu": 0})
    tx = get_tx_history(history)

    for i in range(len(tx) - 3):
        seq = tuple(tx[i:i+3])
        mapping[seq][tx[i+3]] += 1

    return mapping

# ===== AI CORE =====
def ai_predict(user):
    history = user["history"]
    tx = get_tx_history(history)

    if len(tx) < 5:
        return None, 0.5  # chưa đủ dữ liệu

    score = {"Tài": 0.0, "Xỉu": 0.0}

    # MARKOV
    mapping = build_markov(history)
    key = tuple(tx[-3:])
    if key in mapping:
        data = mapping[key]
        total = data["Tài"] + data["Xỉu"]
        if total > 0:
            score["Tài"] += data["Tài"] / total * 2
            score["Xỉu"] += data["Xỉu"] / total * 2

    # TREND
    last5 = tx[-5:]
    score["Tài"] += last5.count("Tài") * 0.4
    score["Xỉu"] += last5.count("Xỉu") * 0.4

    # STREAK
    streak = 1
    for i in range(len(tx)-1, 0, -1):
        if tx[i] == tx[i-1]:
            streak += 1
        else:
            break

    last = tx[-1]
    if streak >= 3:
        score[last] += streak * 1.2
    else:
        opposite = "Tài" if last == "Xỉu" else "Xỉu"
        score[opposite] += 0.6

    # MOMENTUM
    if len(tx) >= 3 and tx[-1] == tx[-2] == tx[-3]:
        score[tx[-1]] += 1.5

    # FREQUENCY
    score["Tài"] += tx.count("Tài") / len(tx)
    score["Xỉu"] += tx.count("Xỉu") / len(tx)

    # AI LEARNING
    score["Tài"] *= user["ai_bias"]["Tài"]
    score["Xỉu"] *= user["ai_bias"]["Xỉu"]

    total_score = score["Tài"] + score["Xỉu"]
    if total_score == 0:
        return None, 0.5

    pred = "Tài" if score["Tài"] > score["Xỉu"] else "Xỉu"
    confidence = max(score.values()) / total_score

    # LEARNING UPDATE
    if user["last_result"] is not None:
        if user["last_pred"] == user["last_result"]:
            user["ai_bias"][user["last_pred"]] *= 1.02
        else:
            user["ai_bias"][user["last_pred"]] *= 0.98

    user["ai_bias"]["Tài"] = min(max(user["ai_bias"]["Tài"], 0.7), 1.3)
    user["ai_bias"]["Xỉu"] = min(max(user["ai_bias"]["Xỉu"], 0.7), 1.3)

    # FLIP NHẸ
    if random.random() < 0.2:
        pred = "Xỉu" if pred == "Tài" else "Tài"

    confidence = max(0.5, min(0.9, confidence))

    # ===== 🔥 SKIP LOGIC =====
    if confidence < 0.6:
        return None, confidence  # bỏ kèo

    return pred, confidence

# ===== BET =====
def calculate_bet(user):
    base = user["money"] * 0.03

    if user["lose"] == 0:
        return int(base)

    bet = base * (1.6 ** user["lose"])

    return int(min(bet, user["money"] * 0.4))

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 AI CASINO MAX\n/setmoney 500000")

async def setmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    m = int(context.args[0])

    users[uid] = {
        "money": m,
        "start_money": m,
        "win": 0,
        "lose": 0,
        "last_pred": None,
        "last_result": None,
        "last_bet": 0,
        "history": [],
        "ai_bias": {"Tài": 1.0, "Xỉu": 1.0}
    }

    await update.message.reply_text(f"💰 {money(m)}")

# ===== HANDLE =====
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id

    if uid not in users:
        return

    user = users[uid]
    text = update.message.text.replace("-", " ")

    nums = [int(x) for x in text.split() if x.isdigit()]
    if len(nums) != 3:
        return

    dice = nums
    real = classify_total(sum(dice))
    user["last_result"] = real

    if user["last_pred"]:
        if user["last_pred"] == real:
            user["money"] += user["last_bet"]
            user["win"] += 1
            user["lose"] = 0
        else:
            user["money"] -= user["last_bet"]
            user["lose"] += 1

    user["history"].append(dice)

    pred, conf = ai_predict(user)

    if pred is None:
        await update.message.reply_text(
            f"🎲 {dice} → {real}\n⚠️ SKIP (kèo yếu)"
        )
        return

    bet = calculate_bet(user)

    user["last_pred"] = pred
    user["last_bet"] = bet

    msg = (
        f"🎲 {dice} → {real}\n"
        f"🔮 {pred} ({conf*100:.1f}%)\n"
        f"💰 {money(bet)}\n"
        f"💼 {money(user['money'])}\n"
        f"🏆 {user['win']} | ❌ {user['lose']}"
    )

    await update.message.reply_text(msg)

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmoney", setmoney))
    app.add_handler(MessageHandler(filters.TEXT, handle))

    app.run_polling()

if __name__ == "__main__":
    main()
