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

# ===== CONFIG =====
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise Exception("❌ Thiếu TOKEN")

users = {}

STRATEGIES = [
    "MARKOV","TREND","ANTI","RANDOM","CHAOS",
    "STREAK","FOLLOW","OPPOSITE","WEIGHTED","PATTERN"
]

# ===== FORMAT =====
def money(x):
    return f"{int(x):,}".replace(",", ".")

def classify(total):
    return "Tài" if total >= 11 else "Xỉu"

def get_tx(history):
    return [classify(sum(x)) for x in history]

# ===== STRATEGIES =====
def markov(history):
    tx = get_tx(history)
    if len(tx) < 4:
        return None
    mapping = defaultdict(lambda: {"Tài":1,"Xỉu":1})
    for i in range(len(tx)-3):
        seq = tuple(tx[i:i+3])
        mapping[seq][tx[i+3]] += 1
    key = tuple(tx[-3:])
    d = mapping[key]
    return "Tài" if d["Tài"] > d["Xỉu"] else "Xỉu"

def trend(tx):
    if len(tx)<5: return None
    last = tx[-5:]
    if last.count("Tài")>=4: return "Tài"
    if last.count("Xỉu")>=4: return "Xỉu"

def anti(tx):
    t = trend(tx)
    if t: return "Xỉu" if t=="Tài" else "Tài"

def chaos(tx):
    if len(tx)>0 and random.random()<0.5:
        return tx[-1]
    return random.choice(["Tài","Xỉu"])

def streak(tx):
    if len(tx)>=2 and tx[-1]==tx[-2]:
        return "Xỉu" if tx[-1]=="Tài" else "Tài"

def follow(tx):
    if len(tx)>=1: return tx[-1]

def opposite(tx):
    if len(tx>=1):
        return "Xỉu" if tx[-1]=="Tài" else "Tài"

def weighted(tx):
    c = Counter(tx)
    return "Tài" if c["Tài"]>c["Xỉu"] else "Xỉu"

def pattern(tx):
    if len(tx)>=4:
        p = tx[-4:]
        if p == ["Tài","Xỉu","Tài","Xỉu"]: return "Tài"
        if p == ["Xỉu","Tài","Xỉu","Tài"]: return "Xỉu"

# ===== RUN STRATEGY =====
def run_strategy(name, history):
    tx = get_tx(history)

    if name=="MARKOV": return markov(history)
    if name=="TREND": return trend(tx)
    if name=="ANTI": return anti(tx)
    if name=="RANDOM": return random.choice(["Tài","Xỉu"])
    if name=="CHAOS": return chaos(tx)
    if name=="STREAK": return streak(tx)
    if name=="FOLLOW": return follow(tx)
    if name=="OPPOSITE": return opposite(tx)
    if name=="WEIGHTED": return weighted(tx)
    if name=="PATTERN": return pattern(tx)

# ===== CHỌN STRATEGY =====
def choose_strategy(user):
    scores = user["strategy_score"]

    if random.random() < 0.7:
        return max(scores, key=lambda k: (scores[k]["win"] - scores[k]["lose"]))

    return random.choice(STRATEGIES)

# ===== AI =====
def ai_predict(user):
    strategy = choose_strategy(user)
    user["strategy"] = strategy

    pred = run_strategy(strategy, user["history"])

    if not pred:
        pred = random.choice(["Tài","Xỉu"])

    if user["lose"]>=1:
        pred = "Xỉu" if pred=="Tài" else "Tài"

    if user["lose"]>=3 and random.random()<0.5:
        return None, 0.5

    return pred, 0.6

# ===== BET =====
def bet_calc(user):
    base = user["money"]*0.04

    if user["lose"]==0:
        return int(base)
    if user["lose"]==1:
        return int(base*0.5)

    return int(min(base*(1.5**user["lose"]), user["money"]*0.3))

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 AI PRO MAX\n💰 /setmoney 500000")

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
        "strategy": None,
        "strategy_score": {s:{"win":0,"lose":0} for s in STRATEGIES}
    }

    await update.message.reply_text(f"💰 Vốn: {money(m)}")

# ===== HANDLE =====
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    if uid not in users:
        await update.message.reply_text("❗ /setmoney trước")
        return

    user = users[uid]

    nums = [int(x) for x in text.replace("-", " ").split() if x.isdigit()]
    if len(nums)!=3:
        await update.message.reply_text("❗ Nhập: 3-5-6")
        return

    dice = nums
    real = classify(sum(dice))

    msg_wait = await update.message.reply_text("⏳ AI đang phân tích...")
    await asyncio.sleep(1)

    user["history"].append(dice)
    if len(user["history"]) > 50:
        user["history"].pop(0)

    result_text="..."

    if user["last_pred"]:
        if user["last_pred"]==real:
            user["money"]+=user["last_bet"]
            user["profit"]+=user["last_bet"]
            user["win"]+=1
            user["lose"]=0
            user["strategy_score"][user["strategy"]]["win"]+=1
            result_text="✅ WIN"
        else:
            user["money"]-=user["last_bet"]
            user["profit"]-=user["last_bet"]
            user["lose"]+=1
            user["strategy_score"][user["strategy"]]["lose"]+=1
            result_text="❌ LOSE"

    pred, conf = ai_predict(user)
    bet = bet_calc(user)

    if pred is None:
        await msg_wait.edit_text("⏸ AI né cầu xấu")
        return

    user["last_pred"]=pred
    user["last_bet"]=bet

    percent = ((user["money"] - user["start"]) / user["start"]) * 100

    status = "🟢 Ổn định"
    if user["lose"] >= 1:
        status = "🟡 Đang điều chỉnh"
    if user["lose"] >= 3:
        status = "🔴 Nguy hiểm"

    msg = (
        "╔══════════════════╗\n"
        "   🤖 AI PRO MAX\n"
        "╚══════════════════╝\n\n"

        f"🎲 Xúc xắc: {dice}\n"
        f"📌 Kết quả: {real}\n\n"

        f"{result_text}\n"
        "━━━━━━━━━━━━━━\n"

        f"🧠 Chiến thuật: {user['strategy']}\n"
        f"🔮 Dự đoán: {pred}\n"
        f"📊 Độ tin cậy: {conf*100:.1f}%\n\n"

        f"💰 Vốn: {money(user['money'])}\n"
        f"📈 Lợi nhuận: {money(user['profit'])}\n"
        f"📊 Tăng/giảm: {percent:.1f}%\n\n"

        f"📉 Trạng thái: {status}\n"
        f"🏆 Thắng: {user['win']} | ❌ Thua: {user['lose']}\n"

        "━━━━━━━━━━━━━━\n"
        "⚡ AI đang tự tối ưu chiến thuật"
    )

    await msg_wait.edit_text(msg)

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmoney", setmoney))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("🔥 AI PRO MAX RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
