import os
import random
import logging
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ===== CONFIG =====
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise Exception("❌ Thiếu TOKEN")

users = {}

# ===== FORMAT =====
def money(x):
    return f"{int(x):,}"

# ===== INIT USER =====
def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "money": 10000,
            "history": [],
            "win": 0,
            "lose": 0,
            "ai_bias": {"Tài": 1.0, "Xỉu": 1.0},
            "last_pred": None,
            "flip_streak": 0
        }
    return users[user_id]

# ===== TÀI/XỈU =====
def get_tx(dice):
    return "Tài" if sum(dice) >= 11 else "Xỉu"

def get_tx_history(history):
    return [get_tx(h["dice"]) for h in history]

# ===== MARKOV =====
def build_markov(history):
    mapping = defaultdict(lambda: {"Tài": 1, "Xỉu": 1})
    tx = get_tx_history(history)

    for i in range(len(tx)-3):
        key = tuple(tx[i:i+3])
        nxt = tx[i+3]
        mapping[key][nxt] += 1

    return mapping

# ===== AI PREDICT =====
def ai_predict(user):
    history = user["history"]
    tx = get_tx_history(history)

    if len(tx) < 5:
        return random.choice(["Tài", "Xỉu"]), 0.55

    score = {"Tài": 0, "Xỉu": 0}

    # ===== MARKOV =====
    mapping = build_markov(history)
    key = tuple(tx[-3:])
    if key in mapping:
        data = mapping[key]
        total = data["Tài"] + data["Xỉu"]
        score["Tài"] += data["Tài"] / total * 2
        score["Xỉu"] += data["Xỉu"] / total * 2

    # ===== TREND =====
    last5 = tx[-5:]
    score["Tài"] += last5.count("Tài") * 0.3
    score["Xỉu"] += last5.count("Xỉu") * 0.3

    # ===== STREAK =====
    streak = 1
    for i in range(len(tx)-1, 0, -1):
        if tx[i] == tx[i-1]:
            streak += 1
        else:
            break

    last = tx[-1]
    if streak >= 3:
        score[last] += streak * 0.8
    else:
        opposite = "Tài" if last == "Xỉu" else "Xỉu"
        score[opposite] += 0.5

    # ===== FREQUENCY =====
    total_tai = tx.count("Tài")
    total_xiu = tx.count("Xỉu")

    score["Tài"] += total_tai / len(tx)
    score["Xỉu"] += total_xiu / len(tx)

    # ===== BIAS =====
    score["Tài"] *= user["ai_bias"]["Tài"]
    score["Xỉu"] *= user["ai_bias"]["Xỉu"]

    # ===== DECISION =====
    pred = "Tài" if score["Tài"] > score["Xỉu"] else "Xỉu"
    total_score = score["Tài"] + score["Xỉu"]
    confidence = max(score.values()) / total_score

    # ===== 🔥 REACTIVE AI (THUA 1) =====
    if user["lose"] == 1:
        confidence *= 0.92

        if user["last_pred"]:
            opposite = "Xỉu" if user["last_pred"] == "Tài" else "Tài"
            if random.random() < 0.7:
                pred = opposite

        user["ai_bias"][user["last_pred"]] *= 0.95

        if random.random() < 0.3:
            pred = "Xỉu" if pred == "Tài" else "Tài"

    # ===== 🔥 ANTI-LOSE =====
    if user["lose"] >= 2:
        confidence *= 0.85

    if user["lose"] >= 3:
        pred = "Xỉu" if pred == "Tài" else "Tài"

    if user["lose"] >= 5:
        if random.random() < 0.5:
            return None, confidence

    # ===== NOISE NHẸ =====
    if random.random() > confidence:
        pred = "Xỉu" if pred == "Tài" else "Tài"

    confidence = max(0.52, min(0.92, confidence))

    return pred, confidence

# ===== BET =====
def calculate_bet(user):
    base = user["money"] * 0.03

    if user["lose"] == 0:
        return int(base)

    if user["lose"] == 1:
        return int(base * 0.8)

    if user["lose"] >= 3:
        return int(base)

    bet = base * (1.4 ** user["lose"])
    return int(min(bet, user["money"] * 0.3))

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎯 Bot AI Tài Xỉu\nGửi 3 số ví dụ: 3 4 6")

# ===== HANDLE =====
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)

    try:
        dice = list(map(int, update.message.text.split()))
        if len(dice) != 3:
            return
    except:
        return

    real = get_tx(dice)
    pred, conf = ai_predict(user)

    bet = calculate_bet(user)

    if pred is None:
        await update.message.reply_text("⏸ AI bỏ qua ván này (cầu xấu)")
        return

    win = pred == real

    if win:
        user["money"] += bet
        user["win"] += 1
        user["lose"] = 0
        result = "✅ WIN"
    else:
        user["money"] -= bet
        user["lose"] += 1
        result = "❌ LOSE"

    user["history"].append({"dice": dice})
    user["last_pred"] = pred

    text = (
        f"🎲 {dice} → {real}\n"
        f"🔮 {pred} ({conf*100:.1f}%)\n"
        f"{result}\n"
        f"💰 Cược: {money(bet)}\n"
        f"💼 Vốn: {money(user['money'])}\n"
        f"📉 Thua: {user['lose']}"
    )

    await update.message.reply_text(text)

# ===== MAIN =====
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

app.run_polling()
