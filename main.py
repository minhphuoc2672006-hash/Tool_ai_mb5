import telebot
import pickle
import os

# ================= ENV =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID") or "0")

if not TOKEN:
    raise Exception("Thiếu BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

# ================= DATA =================
history = []

MAX_HISTORY = 300  # 🔥 chống lệch lâu dài

# ================= LOAD MODEL =================
def load_model():
    try:
        with open("model.pkl", "rb") as f:
            return pickle.load(f)
    except:
        return {}

model = load_model()

# ================= CHECK ADMIN =================
def is_admin(msg):
    return msg.from_user.id == ADMIN_ID

# ================= PARSE =================
def parse_input(text):
    try:
        if "-" in text:
            return [int(x) for x in text.split("-") if x.strip().isdigit()]
        return [int(text)]
    except:
        return []

# ================= CONVERT =================
def to_tx(num):
    return 1 if num >= 11 else 0

# ================= PATTERN =================
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

# ================= CYCLE =================
def detect_cycle():
    if len(history) < 8:
        return "Không rõ"

    seq = history[-8:]

    if seq[:4] == seq[4:]:
        return "Chu kỳ lặp 4"

    return "Nhiễu"

# ================= AI (FIXED MARKOV) =================
def predict_ai():
    if len(history) < 3:
        return None, 0

    key = tuple(history[-3:])

    if key in model:
        t, x = model[key]
        total = t + x

        if total < 2:
            return None, 0.5

        prob_t = t / total
        prob_x = x / total

        # 🔥 nếu quá sát nhau → bỏ AI
        if abs(prob_t - prob_x) < 0.08:
            return None, 0.5

        return (1 if prob_t > prob_x else 0), max(prob_t, prob_x)

    return None, 0.5

# ================= TRAIN =================
def train_model():
    if not os.path.exists("data.txt"):
        return model

    data = []

    with open("data.txt") as f:
        for line in f:
            try:
                data.append(to_tx(int(line.strip())))
            except:
                continue

    new_model = {}

    for i in range(len(data) - 3):
        key = tuple(data[i:i+3])
        nxt = data[i+3]

        if key not in new_model:
            new_model[key] = [0, 0]

        new_model[key][nxt] += 1

    with open("model.pkl", "wb") as f:
        pickle.dump(new_model, f)

    return new_model

# ================= ANTI BIAS =================
def get_bias():
    if len(history) < 10:
        return 0.5
    return sum(history) / len(history)

# ================= VOTE (FIXED) =================
def vote(pattern, cycle, ai):
    if not history:
        return "Không rõ", 0.5

    score_t = 0
    score_x = 0

    last = history[-1]

    # ===== PATTERN =====
    if pattern == "Bệt":
        score_t += 2 if last == 1 else 0
        score_x += 2 if last == 0 else 0

    elif pattern == "1-1":
        score_t += 2 if last == 0 else 0
        score_x += 2 if last == 1 else 0

    elif pattern == "2-2":
        score_t += 1
        score_x += 1

    # ===== CYCLE =====
    if "lặp" in cycle:
        score_t += 0.5 if last == 1 else 0
        score_x += 0.5 if last == 0 else 0

    # ===== AI (GIẢM ẢNH HƯỞNG) =====
    if ai is not None:
        score_t += 1.5 if ai == 1 else 0
        score_x += 1.5 if ai == 0 else 0

    # ===== ANTI BIAS FIX =====
    bias = get_bias()

    if bias > 0.65:
        score_x += 0.8
    elif bias < 0.35:
        score_t += 0.8

    total = score_t + score_x

    if total == 0:
        return "Không rõ", 0.5

    prob_t = score_t / total

    if abs(prob_t - 0.5) < 0.05:
        return "Không rõ", 0.5

    return ("TÀI", prob_t) if prob_t > 0.5 else ("XỈU", 1 - prob_t)

# ================= START =================
@bot.message_handler(commands=['start'])
def start(msg):
    if not is_admin(msg):
        return
    bot.reply_to(msg, "BOT AI PRO FIXED + ANTI-BIAS 🚀")

# ================= RESET =================
@bot.message_handler(commands=['reset'])
def reset(msg):
    if not is_admin(msg):
        return
    history.clear()
    bot.reply_to(msg, "Reset xong")

# ================= HANDLE =================
@bot.message_handler(func=lambda m: True)
def handle(msg):
    global model

    if not is_admin(msg):
        return

    nums = parse_input(msg.text)

    if not nums:
        bot.reply_to(msg, "Sai định dạng")
        return

    for num in nums:
        if 3 <= num <= 18:
            history.append(to_tx(num))

            with open("data.txt", "a") as f:
                f.write(str(num) + "\n")

    # 🔥 chống drift
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    # auto train
    if len(history) % 200 == 0:
        model = train_model()

    pattern = detect_pattern()
    cycle = detect_cycle()
    ai, _ = predict_ai()
    result, conf = vote(pattern, cycle, ai)

    bot.reply_to(msg,
f"""
KQ: {nums[-1]}

Cầu: {pattern}
Chu kỳ: {cycle}

AI: {"TÀI" if ai==1 else "XỈU" if ai==0 else "??"}

=> Dự đoán: {result}
Tin cậy: {round(conf*100)}%
"""
    )

# ================= RUN =================
bot.polling()
