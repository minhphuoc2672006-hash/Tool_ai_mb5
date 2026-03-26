# ====== GIỮ NGUYÊN IMPORT ======
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

# ===== FORMAT =====
def money(x):
    return f"{int(x):,}".replace(",", ".")

# ===== PHÂN LOẠI =====
def classify_total(total):
    return "Tài" if total >= 11 else "Xỉu"

def get_tx_history(history):
    return [classify_total(sum(x)) for x in history]

# ===== GIỮ NGUYÊN MARKOV =====
def build_markov(history):
    mapping = defaultdict(lambda: {"Tài": 0, "Xỉu": 0})
    tx = get_tx_history(history)

    for i in range(len(tx) - 3):
        seq = tuple(tx[i:i+3])
        mapping[seq][tx[i+3]] += 1

    return mapping

# ===== GIỮ NGUYÊN TREND =====
def analyze_trend(tx):
    if len(tx) < 5:
        return None

    last5 = tx[-5:]
    if last5.count("Tài") >= 4:
        return "Tài"
    if last5.count("Xỉu") >= 4:
        return "Xỉu"
    return None

# ===== MA TRẬN NGHỊCH ĐẢO =====
def inverse_matrix(tx):
    matrix = {"Tài":{"Tài":1,"Xỉu":1},"Xỉu":{"Tài":1,"Xỉu":1}}

    for i in range(len(tx)-1):
        matrix[tx[i]][tx[i+1]] += 1

    last = tx[-1]

    # đảo xác suất
    inv_tai = matrix[last]["Xỉu"]
    inv_xiu = matrix[last]["Tài"]

    return "Tài" if inv_tai > inv_xiu else "Xỉu"

# ===== 200 CHIẾN THUẬT =====
def mega_advanced(tx):

    results = []

    if len(tx) < 3:
        return [random.choice(["Tài","Xỉu"])]

    # ===== 100 CAO CẤP =====
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
            # anti trap
            last6 = tx[-6:] if len(tx)>=6 else tx
            if last6.count("Tài") > last6.count("Xỉu"):
                results.append("Xỉu")
            else:
                results.append("Tài")

    # ===== 100 BIẾN THỂ =====
    for i in range(100):

        last5 = tx[-5:]
        tai = last5.count("Tài")
        xiu = last5.count("Xỉu")

        if tai > xiu:
            results.append("Tài" if i%2==0 else "Xỉu")
        else:
            results.append("Xỉu" if i%2==0 else "Tài")

    return results

# ===== AI CHÍNH (GIỮ NGUYÊN + THÊM) =====
def ai_predict(user):
    history = user["history"]
    tx = get_tx_history(history)
    mapping = build_markov(history)

    markov_pred = None
    confidence = 0

    # ===== MARKOV GỐC =====
    if len(tx) >= 3:
        key = tuple(tx[-3:])
        data = mapping[key]
        total = data["Tài"] + data["Xỉu"]

        if total > 0:
            markov_pred = "Tài" if data["Tài"] > data["Xỉu"] else "Xỉu"
            confidence = max(data["Tài"], data["Xỉu"]) / total

    # ===== TREND =====
    trend_pred = analyze_trend(tx)

    # ===== COMBINE GỐC =====
    if markov_pred and trend_pred:
        pred = markov_pred if markov_pred == trend_pred else markov_pred
    elif markov_pred:
        pred = markov_pred
    elif trend_pred:
        pred = trend_pred
    else:
        pred = random.choice(["Tài","Xỉu"])

    # ===== THÊM: INVERSE MATRIX =====
    inv_pred = inverse_matrix(tx) if len(tx)>=2 else pred

    # ===== THÊM: 200 STRATEGIES =====
    extra = mega_advanced(tx)
    count = Counter(extra)
    extra_pred = "Tài" if count["Tài"] > count["Xỉu"] else "Xỉu"

    # ===== VOTE TỔNG =====
    votes = [pred, inv_pred, extra_pred]
    final = Counter(votes)
    pred = "Tài" if final["Tài"] > final["Xỉu"] else "Xỉu"

    # ===== CONTROL CASINO =====
    winrate = user["win"] / (user["win"] + user["lose"] + 1)

    if winrate > 0.65:
        confidence -= 0.1
    elif winrate < 0.45:
        confidence += 0.1

    confidence = max(0.52, min(0.93, confidence))

    if random.random() > confidence:
        pred = "Xỉu" if pred == "Tài" else "Tài"

    return pred, confidence

# ===== BET (GIỮ NGUYÊN) =====
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

# ===== TELEGRAM GIỮ NGUYÊN =====
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

# ===== HANDLE GIỮ NGUYÊN =====
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
