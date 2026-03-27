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

# ===== FORMAT TIỀN =====
def money(x):
    return f"{int(x):,}".replace(",", ".")

# ===== PHÂN LOẠI TÀI/XỈU =====
def classify_total(total):
    return "Tài" if total >= 11 else "Xỉu"

def get_tx_history(history):
    return [classify_total(sum(x)) for x in history]

# ===== NHẬN DIỆN CÁC LOẠI CẦU LOGIC =====
def analyze_patterns(history):
    if not history:
        return {}
    tx = get_tx_history(history)
    patterns = defaultdict(int)

    # Cầu bệt
    for dice in history[-3:]:
        if dice[0] == dice[1] == dice[2]:
            patterns["bệt"] += 1

    # Cầu dài
    if len(tx) >= 4:
        last4 = tx[-4:]
        if last4.count(last4[0]) == 4:
            patterns["dài"] += 1

    # Cầu nối
    for i in range(len(tx)-3):
        if tx[i:i+2] == tx[i+2:i+4]:
            patterns["nối"] += 1

    # Cầu chu kỳ
    for i in range(len(tx)-3):
        cycle = tx[i:i+4]
        if cycle[0]==cycle[2] and cycle[1]==cycle[3]:
            patterns["chu kỳ"] += 1

    # Zigzag
    for i in range(len(tx)-1):
        if tx[i]!=tx[i+1]:
            patterns["zigzag"] += 1

    # Cầu phức tạp
    for i in range(len(tx)-5):
        pattern = tx[i:i+6]
        if pattern[0]==pattern[2] and pattern[1]==pattern[3] and pattern[4]!=pattern[5]:
            patterns["phức tạp"] += 1

    return patterns

# ===== DETECT NGHỊCH ĐẢO =====
def detect_inverse_hand(history):
    tx = get_tx_history(history)
    if len(tx) < 5:
        return False
    flips = sum(1 for i in range(1, len(tx)) if tx[i] != tx[i-1])
    return flips >= len(tx) * 0.7

# ===== STRATEGIES =====
STRATEGIES = [
    "FOLLOW","OPPOSITE","TREND","RANDOM",
    "STREAK","ANTI_STREAK","WEIGHTED",
    "LAST2","ALT","BREAK","CHAOS"
]

def run_strategy(name, history):
    tx = get_tx_history(history)
    if not tx:
        return random.choice(["Tài","Xỉu"])
    if name == "FOLLOW": return tx[-1]
    if name == "OPPOSITE": return "Xỉu" if tx[-1]=="Tài" else "Tài"
    if name == "TREND":
        if len(tx)>=4:
            return "Tài" if tx[-4:].count("Tài") > tx[-4:].count("Xỉu") else "Xỉu"
    if name == "STREAK":
        if len(tx)>=2 and tx[-1]==tx[-2]: return tx[-1]
    if name == "ANTI_STREAK":
        if len(tx)>=2 and tx[-1]==tx[-2]:
            return "Xỉu" if tx[-1]=="Tài" else "Tài"
    if name == "WEIGHTED":
        c = Counter(tx)
        return "Tài" if c["Tài"] > c["Xỉu"] else "Xỉu"
    if name == "LAST2":
        if len(tx)>=2: return tx[-2]
    if name == "ALT":
        if len(tx)>=2: return "Xỉu" if tx[-1]==tx[-2] else tx[-1]
    if name == "BREAK":
        if len(tx)>=3 and tx[-1]==tx[-2]==tx[-3]: return "Xỉu" if tx[-1]=="Tài" else "Tài"
    if name == "CHAOS": return random.choice(tx)
    return random.choice(["Tài","Xỉu"])

def pick_strategy():
    return random.choice(STRATEGIES)

# ===== AI DỰ ĐOÁN =====
def ai_predict(user):
    history = user["history"]
    if len(history) < 5:
        return None, None  # Chưa đủ lịch sử
    tx = get_tx_history(history)
    patterns = analyze_patterns(history)
    votes = []

    # Dựa trên mẫu cầu
    if patterns:
        if patterns.get("bệt",0): votes.append("Xỉu")
        if patterns.get("dài",0): votes.append(tx[-1])
        if patterns.get("nối",0): votes.append("Tài" if tx[-1]=="Xỉu" else "Xỉu")
        if patterns.get("chu kỳ",0): votes.append(tx[-1])
        if patterns.get("zigzag",0): votes.append("Tài" if tx[-1]=="Tài" else "Xỉu")
        if patterns.get("phức tạp",0): votes.append(tx[-1])

    # Markov 3 bậc
    if len(tx)>=3:
        key = tuple(tx[-3:])
        counts = Counter()
        for i in range(len(tx)-3):
            if tuple(tx[i:i+3]) == key: counts[tx[i+3]] += 1
        if counts:
            markov_pred = "Tài" if counts["Tài"]>counts["Xỉu"] else "Xỉu"
            votes.append(markov_pred)

    # Trend last5
    if len(tx)>=5:
        last5 = tx[-5:]
        if last5.count("Tài")>=4: votes.append("Tài")
        elif last5.count("Xỉu")>=4: votes.append("Xỉu")

    # Mega Strategy last6
    if len(tx)>=6:
        last6 = tx[-6:]
        tai = last6.count("Tài")
        xiu = last6.count("Xỉu")
        votes.append("Tài" if tai>xiu else "Xỉu")

    # Inverse detection
    if detect_inverse_hand(history):
        votes.append("Xỉu" if votes[-1]=="Tài" else "Tài")

    # Vote cuối cùng
    if votes:
        count = Counter(votes)
        pred = "Tài" if count["Tài"] >= count["Xỉu"] else "Xỉu"
        conf = count[pred]/len(votes)
    else:
        pred = random.choice(["Tài","Xỉu"])
        conf = 0.5

    # Điều chỉnh theo winrate
    winrate = user["win"] / (user["win"] + user["lose"] + 1)
    if winrate>0.65: conf-=0.1
    elif winrate<0.45: conf+=0.1
    conf = max(0.51, min(0.95, conf))

    # Ẩn random kiểu casino
    if random.random()>conf:
        pred = "Tài" if pred=="Xỉu" else "Xỉu"

    return pred, conf

# ===== TÍNH TIỀN CƯỢC GẤP THÉP =====
def calculate_bet(user):
    base_money = user["money"]
    base_percent = 0.05
    if user.get("lose",0)==0:
        bet = base_money*base_percent
    else:
        bet = base_money*base_percent*(2**(user["lose"]-1))
    bet = min(int(base_money*0.9), int(bet))
    return max(1, bet)

def calculate_percent(conf):
    return conf*100

# ===== TELEGRAM COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI CASINO PRO MAX 6.0\n\n"
        "💰 /setmoney 1000\n"
        "🔄 /reset\n"
        "💣 /resetall\n\n"
        "📥 Nhập: 3-5-6 (3 viên xí ngầu)"
    )

async def setmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    try: m = int(context.args[0])
    except: await update.message.reply_text("❗ /setmoney 1000"); return
    users[uid] = {
        "money": m,
        "start_money": m,
        "profit": 0,
        "win": 0,
        "lose": 0,
        "last_pred": None,
        "last_bet": 0,
        "history": [],
        "strategy": pick_strategy()
    }
    await update.message.reply_text(f"💰 Vốn: {money(m)}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid in users:
        start_money = users[uid]["start_money"]
        users[uid] = {
            "money": start_money,
            "start_money": start_money,
            "profit":0,
            "win":0,
            "lose":0,
            "last_pred":None,
            "last_bet":0,
            "history":[],
            "strategy": pick_strategy()
        }
    await update.message.reply_text("🔄 Reset xong")

async def resetall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid in users: del users[uid]
    await update.message.reply_text("💣 Xoá toàn bộ")

# ===== HANDLE MESSAGE =====
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.strip()
    if uid not in users:
        await update.message.reply_text("❗ /setmoney trước"); return
    user = users[uid]

    for c in ["-", ",", "|"]: text = text.replace(c," ")
    nums = [int(x) for x in text.split() if x.isdigit() and 1<=int(x)<=6]
    if len(nums)!=3:
        await update.message.reply_text("❗ Nhập dạng: 3-5-6"); return
    dice = nums
    real = classify_total(sum(dice))

    msg_wait = await update.message.reply_text("⏳ AI đang phân tích...")
    await asyncio.sleep(1)

    # Lưu lịch sử
    user["history"].append(dice)
    if len(user["history"])>50: user["history"].pop(0)

    # WIN/LOSE
    result_text = "..."
    if user["last_pred"] is not None:
        if user["last_pred"]==real:
            user["money"] += user["last_bet"]
            user["profit"] += user["last_bet"]
            user["win"] += 1
            user["lose"] = 0
            result_text = "✅ WIN"
        else:
            user["money"] -= user["last_bet"]
            user["profit"] -= user["last_bet"]
            user["lose"] += 1
            # 🔥 THUA 1 → ĐỔI NGAY CHIẾN THUẬT
            user["strategy"] = pick_strategy()
            result_text = "❌ LOSE"

    # AI dự đoán
    pred, conf = ai_predict(user)
    if pred is None:
        await msg_wait.edit_text(
            "━━━━━━━━━━━━━━\n"
            "🤖 AI CASINO PRO MAX 6.0\n"
            "━━━━━━━━━━━━━━\n"
            "⚠️ Chưa đủ lịch sử (ít nhất 5 lượt) để dự đoán\n"
            "━━━━━━━━━━━━━━"
        )
        user["last_pred"] = None
        user["last_bet"] = 0
        return

    bet = calculate_bet(user)
    if user["money"]<=0: await update.message.reply_text("🛑 HẾT TIỀN"); return
    user["last_pred"] = pred
    user["last_bet"] = bet

    msg = (
        "━━━━━━━━━━━━━━\n"
        "🤖 AI CASINO PRO MAX 6.0\n"
        "━━━━━━━━━━━━━━\n"
        f"🎲 {dice} → {real}\n"
        f"{result_text}\n"
        "──────────────\n"
        f"🔮 Dự đoán lần tới: {pred}\n"
        f"📊 Xác suất: {calculate_percent(conf):.1f}%\n"
        f"💸 Tiền cược: {money(bet)}\n"
        f"💰 Vốn: {money(user['money'])}\n"
        f"📈 Lãi: {money(user['profit'])}\n"
        "──────────────\n"
        f"🏆 Win | ❌ Lose: {user['win']} | {user['lose']}\n"
        f"Chiến thuật: {user['strategy']}\n"
        "━━━━━━━━━━━━━━"
    )
    await msg_wait.edit_text(msg)

# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setmoney", setmoney))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("resetall", resetall))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    print("🔥 AI CASINO PRO MAX 6.0 RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
