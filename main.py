import telebot
import pickle
import os

# ===== ENV (ẨN TOKEN) =====
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = telebot.TeleBot(TOKEN)

history = []

# ===== LOAD MODEL =====
def load_model():
    global model
    try:
        with open("model.pkl", "rb") as f:
            model = pickle.load(f)
    except:
        model = {}

load_model()

# ===== CHECK ADMIN =====
def is_admin(msg):
    return msg.from_user.id == ADMIN_ID

# ===== CẦU =====
def detect_pattern():
    if len(history) < 4:
        return "Chưa rõ"

    last = history[-4:]

    if last == [1,1,1,1] or last == [0,0,0,0]:
        return "Bệt"

    if last == [1,0,1,0] or last == [0,1,0,1]:
        return "1-1"

    if last == [1,1,0,0] or last == [0,0,1,1]:
        return "2-2"

    return "Gãy"

# ===== CHU KỲ SÂU =====
def detect_cycle():
    if len(history) < 8:
        return "Không rõ"

    seq = history[-8:]

    # lặp 4-4
    if seq[:4] == seq[4:]:
        return "Chu kỳ lặp 4"

    # 1-1 dài
    if seq == [1,0,1,0,1,0,1,0] or seq == [0,1,0,1,0,1,0,1]:
        return "Chu kỳ 1-1"

    return "Nhiễu"

# ===== AI =====
def predict_ai():
    if len(history) < 3:
        return None, 0

    key = tuple(history[-3:])

    if key in model:
        t, x = model[key]
        total = t + x

        if total == 0:
            return None, 0

        prob = max(t, x) / total
        return (1 if t > x else 0), prob

    return None, 0

# ===== TRAIN =====
def train_model():
    data = []

    if not os.path.exists("data.txt"):
        return model

    with open("data.txt") as f:
        for line in f:
            try:
                n = int(line.strip())
                tx = 1 if n >= 11 else 0
                data.append(tx)
            except:
                continue

    model_new = {}

    for i in range(len(data)-3):
        key = tuple(data[i:i+3])
        nxt = data[i+3]

        if key not in model_new:
            model_new[key] = [0, 0]

        model_new[key][nxt] += 1

    with open("model.pkl", "wb") as f:
        pickle.dump(model_new, f)

    return model_new

# ===== VOTE =====
def vote(pattern, cycle, ai):
    score_tai = 0
    score_xiu = 0

    # cầu
    if pattern == "Bệt":
        if history[-1] == 1:
            score_tai += 2
        else:
            score_xiu += 2

    if pattern == "1-1":
        if history[-1] == 1:
            score_xiu += 2
        else:
            score_tai += 2

    if pattern == "2-2":
        score_tai += 1
        score_xiu += 1

    # chu kỳ
    if "lặp" in cycle:
        if history[-1] == 1:
            score_tai += 1
        else:
            score_xiu += 1

    # AI
    if ai is not None:
        if ai == 1:
            score_tai += 3
        else:
            score_xiu += 3

    total = score_tai + score_xiu
    if total == 0:
        return "Không rõ", 0

    if score_tai > score_xiu:
        return "TÀI", score_tai / total
    else:
        return "XỈU", score_xiu / total

# ===== START =====
@bot.message_handler(commands=['start'])
def start(msg):
    if not is_admin(msg):
        return

    bot.reply_to(msg, "BOT AI PRO READY")

# ===== RESET =====
@bot.message_handler(commands=['reset'])
def reset(msg):
    if not is_admin(msg):
        return

    history.clear()
    bot.reply_to(msg, "Đã reset")

# ===== HANDLE =====
@bot.message_handler(func=lambda m: True)
def handle(msg):
    global model

    if not is_admin(msg):
        return

    try:
        num = int(msg.text)

        if num < 3 or num > 18:
            bot.reply_to(msg, "Nhập 3-18")
            return

        tx = 1 if num >= 11 else 0
        history.append(tx)

        # lưu data
        with open("data.txt", "a") as f:
            f.write(str(num) + "\n")

        # AUTO TRAIN (tối ưu)
        with open("data.txt") as f:
            lines = f.readlines()

        if len(lines) % 200 == 0:
            model = train_model()

        pattern = detect_pattern()
        cycle = detect_cycle()
        ai, prob_ai = predict_ai()

        result, confidence = vote(pattern, cycle, ai)

        bot.reply_to(msg,
f"""
KQ: {num}

Cầu: {pattern}
Chu kỳ: {cycle}

AI: {"TÀI" if ai==1 else "XỈU" if ai==0 else "??"}

=> Dự đoán: {result}
Tin cậy: {round(confidence*100)}%
"""
        )

    except:
        bot.reply_to(msg, "Sai định dạng")

bot.polling()
