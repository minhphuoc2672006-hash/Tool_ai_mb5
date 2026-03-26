# ====== IMPORT ======
import os
import logging
import asyncio
import random
from collections import defaultdict, Counter
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

# ===== AI MEMORY (LSTM GIẢ) =====
ai_memory = defaultdict(lambda: {"Tài":0, "Xỉu":0})

def train_ai(tx):
    if len(tx) < 4:
        return
    key = tuple(tx[-4:])
    next_val = tx[-1]
    ai_memory[key][next_val] += 1

def ai_lstm_predict(tx):
    if len(tx) < 4:
        return None, 0

    key = tuple(tx[-4:])
    data = ai_memory[key]
    total = data["Tài"] + data["Xỉu"]

    if total == 0:
        return None, 0

    pred = "Tài" if data["Tài"] > data["Xỉu"] else "Xỉu"
    conf = max(data["Tài"], data["Xỉu"]) / total
    return pred, conf

# ===== FORMAT =====
def money(x):
    return f"{int(x):,}".replace(",", ".")

# ===== PHÂN LOẠI =====
def classify_total(total):
    return "Tài" if total >= 11 else "Xỉu"

def get_tx_history(history):
    return [classify_total(sum(x)) for x in history]

# ===== MARKOV =====
def build_markov(history):
    mapping = defaultdict(lambda: {"Tài": 0, "Xỉu": 0})
    tx = get_tx_history(history)

    for i in range(len(tx) - 3):
        seq = tuple(tx[i:i+3])
        mapping[seq][tx[i+3]] += 1

    return mapping

# ===== TREND =====
def analyze_trend(tx):
    if len(tx) < 5:
        return None
    last5 = tx[-5:]
    if last5.count("Tài") >= 4:
        return "Tài"
    if last5.count("Xỉu") >= 4:
        return "Xỉu"
    return None

# ===== INVERSE =====
def inverse_matrix(tx):
    matrix = {"Tài":{"Tài":1,"Xỉu":1},"Xỉu":{"Tài":1,"Xỉu":1}}
    for i in range(len(tx)-1):
        matrix[tx[i]][tx[i+1]] += 1

    last = tx[-1]
    inv_tai = matrix[last]["Xỉu"]
    inv_xiu = matrix[last]["Tài"]

    return "Tài" if inv_tai > inv_xiu else "Xỉu"

# ===== 200 STRATEGIES =====
def mega_advanced(tx):
    results = []

    if len(tx) < 3:
        return [random.choice(["Tài","Xỉu"])]

    for i in range(100):
        if i % 5 == 0:
            results.append(tx[-1])
        elif i % 5 == 1:
            results.append("Xỉu" if tx[-1]=="Tài" else "Tài")
        elif i % 5 == 2:
            results.append(tx[-2] if len(tx)>=2 else tx[-1])
        elif i % 5 == 3:
            results.append(tx[-3] if len(tx)>=3 else tx[-1])
        else:
            last6 = tx[-6:] if len(tx)>=6 else tx
            if last6.count("Tài") > last6.count("Xỉu"):
                results.append("Xỉu")
            else:
                results.append("Tài")

    for i in range(100):
        last5 = tx[-5:]
        tai = last5.count("Tài")
        xiu = last5.count("Xỉu")

        if tai > xiu:
            results.append("Tài" if i%2==0 else "Xỉu")
        else:
            results.append("Xỉu" if i%2==0 else "Tài")

    return results

# ===== AI MAIN =====
def ai_predict(user):
    history = user["history"]
    tx = get_tx_history(history)

    # TRAIN AI
    train_ai(tx)

    mapping = build_markov(history)

    markov_pred = None
    confidence = 0

    if len(tx) >= 3:
        key = tuple(tx[-3:])
        data = mapping[key]
        total = data["Tài"] + data["Xỉu"]

        if total > 0:
            markov_pred = "Tài" if data["Tài"] > data["Xỉu"] else "Xỉu"
            confidence = max(data["Tài"], data["Xỉu"]) / total

    trend_pred = analyze_trend(tx)

    if markov_pred and trend_pred:
        pred = markov_pred
    elif markov_pred:
        pred = markov_pred
    elif trend_pred:
        pred = trend_pred
    else:
        pred = random.choice(["Tài","Xỉu"])

    inv_pred = inverse_matrix(tx) if len(tx)>=2 else pred

    extra = mega_advanced(tx)
    count = Counter(extra)
    extra_pred = "Tài" if count["Tài"] > count["Xỉu"] else "Xỉu"

    # ===== LSTM =====
    lstm_pred, lstm_conf = ai_lstm_predict(tx)

    # ===== VOTE =====
    votes = [pred, inv_pred, extra_pred]

    if lstm_pred:
        votes.append(lstm_pred)
        confidence = (confidence + lstm_conf) / 2

    final = Counter(votes)
    pred = "Tài" if final["Tài"] > final["Xỉu"] else "Xỉu"

    # ===== CONTROL =====
    winrate = user["win"] / (user["win"] + user["lose"] + 1)

    if winrate > 0.65:
        confidence -= 0.1
    elif winrate < 0.45:
        confidence += 0.1

    confidence = max(0.52, min(0.93, confidence))

    if random.random() > confidence:
        pred = "Xỉu" if pred == "Tài" else "Tài"

    return pred, confidence

# ===== BET =====
def calculate_bet(user):
    base_money = user["money"]
    base_percent = 0.05

    if user["lose"] == 0:
        bet = base_money * base_percent
    else:
        bet = base_money * base_percent * (2 ** (user["lose"] - 1))

    if bet > base_money * 0.9:
        bet = int(base_money * 0.9)
    else:
        bet = int(bet)

    return max(1, bet)

# ===== TELEGRAM =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 AI CASINO PRO MAX")

async def setmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    m = int(context.args[0])

    users[uid] = {
        "money": m,
        "start_money": m,
        "profit": 0,
        "win": 0,
        "lose": 0,
        "last_pred": None,
        "last_bet": 0,
        "history": []
    }

    await update.message.reply_text(f"💰 {money(m)}")

# ===== HANDLE =====
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()

    if uid not in users:
        await update.message.reply_text("❗ /setmoney trước")
        return

    user = users[uid]

    nums = [int(x) for x in text.replace("-", " ").split() if x.isdigit()]

    if len(nums) != 3:
        await update.message.reply_text("❗ 3-5-6")
        return

    dice = nums
    total = sum(dice)
    real = classify_total(total)

    msg_wait = await update.message.reply_text("⏳ AI đang phân tích...")
    await asyncio.sleep(1)

    user["history"].append(dice)
    if len(user["history"]) > 50:
        user["history"].pop(0)

    result_text = "..."
    if user["last_pred"]:
        if user["last_pred"] == real:
            user["money"] += user["last_bet"]
            user["profit"] += user["last_bet"]
            user["win"] += 1
            user["lose"] = 0
            result_text = "✅ WIN"
        else:
            user["money"] -= user["last_bet"]
            user["profit"] -= user["last_bet"]
            user["lose"] += 1
            result_text = "❌ LOSE"

    pred, conf = ai_predict(user)
    bet = calculate_bet(user)

    user["last_pred"] = pred
    user["last_bet"] = bet

    percent_total = ((user["money"] - user["start_money"]) / user["start_money"] * 100)

    msg = (
        "🤖 AI CASINO PRO MAX\n"
        "━━━━━━━━━━━━\n"
        f"🎲 {dice} → {real}\n\n"
        f"{result_text}\n"
        "━━━━━━━━━━━━\n"
        f"🔮 {pred}\n"
        f"📊 {conf*100:.1f}%\n"
        f"💰 {money(bet)}\n"
        "━━━━━━━━━━━━\n"
        f"💼 {money(user['money'])}\n"
        f"📈 {money(user['profit'])}\n"
        f"📊 {percent_total:.1f}%\n"
        "━━━━━━━━━━━━\n"
        f"🏆 {user['win']} | ❌ {user['lose']}"
    )

    await msg_wait.edit_text(msg)

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmoney", setmoney))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("🔥 AI MAX RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
