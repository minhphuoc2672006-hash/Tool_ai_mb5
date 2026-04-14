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

# ================= PARSE INPUT =================
def parse_input(text):
    # nhận: "14-5-10" hoặc "12"
    try:
        if "-" in text:
            return [int(x) for x in text.split("-") if x.strip().isdigit()]
        else:
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

    if seq == [1,0,1,0,1,0,1,0] or seq == [0,1,0,1,0,1,0,1]:
        return "Chu kỳ 1-1"

    return "Nhiễu"

# ================= AI =================
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

# ================= TRAIN =================
def train_model():
    if not os.path.exists("data.txt"):
        return model

    data = []

    with open("data.txt") as f:
        for line in f:
            try:
                n = int(line.strip())
                data.append(to_tx(n))
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

# ================= VOTE =================
def vote(pattern, cycle, ai):
    if not history:
        return "Không rõ", 0

    score_t = 0
    score_x = 0

    last = history[-1]

    # pattern
    if pattern == "Bệt":
        if last == 1:
            score_t += 2
        else:
            score_x += 2

    elif pattern == "1-1":
        if last == 1:
            score_x += 2
        else:
            score_t += 2

    elif pattern == "2-2":
        score_t += 1
        score_x += 1

    # cycle
    if "lặp" in cycle:
        if last == 1:
            score_t += 1
        else:
            score_x += 1

    # AI
    if ai is not None:
        if ai == 1:
            score_t += 3
        else:
            score_x += 3

    total = score_t + score_x

    if total == 0:
        return "Không rõ", 0

    return ("TÀI", score_t/total) if score_t > score_x else ("XỈU", score_x/total)

# ================= START =================
@bot.message_handler(commands=['start'])
def start(msg):
    if not is_admin(msg):
        return
    bot.reply_to(msg, "BOT AI PRO UPGRADED READY 🚀")

# ================= RESET =================
@bot.message_handler(commands=['reset'])
def reset(msg):
    if not is_admin(msg):
        return
    history.clear()
    bot.reply_to(msg, "Đã reset history")

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

        if num < 3 or num > 18:
            continue

        tx = to_tx(num)
        history.append(tx)

        with open("data.txt", "a") as f:
            f.write(str(num) + "\n")

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
