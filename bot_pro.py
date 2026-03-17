import os
from collections import defaultdict
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

history = []

# ===== TX =====
def tx(n):
    return "T" if n >= 11 else "X"

# ===== PARSE =====
def parse(text):
    parts = text.replace(" ", "").split("-")
    return [int(p) for p in parts if p.isdigit()]

# ===== BUILD MEMORY FULL =====
def build_memory():
    memory = defaultdict(list)

    for size in range(3, min(40, len(history))):
        for i in range(len(history) - size):
            pattern = tuple(history[i:i+size])
            next_val = history[i+size]
            memory[pattern].append(next_val)

    return memory

# ===== NHẬN DIỆN CẦU =====
def detect_pattern():
    if len(history) < 4:
        return "Chưa rõ"

    last = history[-4:]

    if all(x == last[0] for x in last):
        return "🔥 Cầu bệt"

    if last == ["T","X","T","X"] or last == ["X","T","X","T"]:
        return "🔁 Cầu 1-1"

    if history[-1] != history[-2] and history[-2] != history[-3]:
        return "⚠️ Đảo liên tục (nguy hiểm)"

    return "Không rõ"

# ===== AI =====
def predict():
    if len(history) < 8:
        return "❌ Chưa đủ dữ liệu"

    memory = build_memory()

    best_score = 0
    best = None
    danger = ""

    for size in range(min(30, len(history)), 3, -1):
        pattern = tuple(history[-size:])

        if pattern in memory:
            data = memory[pattern]

            if len(data) < 4:
                continue

            t = data.count("T")
            x = data.count("X")
            diff = abs(t - x)

            # ❌ bỏ nhiễu
            if diff <= 1:
                continue

            score = diff * size * len(data)

            if score > best_score:
                best_score = score
                best = "TÀI" if t > x else "XỈU"

                # ⚠️ phát hiện cầu bẫy
                if diff < 3:
                    danger = "⚠️ Có dấu hiệu cầu bẫy"

    if not best:
        return "⚠️ Không rõ cầu → đứng ngoài"

    return f"""
🎯 DỰ ĐOÁN: {best}
🔥 Độ mạnh: {best_score}
{danger}
"""

# ===== BOT =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 AI TX PRO MAX - FULL HISTORY")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nums = parse(update.message.text)

    if not nums:
        return await update.message.reply_text("❌ Nhập dạng: 13-14-15")

    added = []

    for n in nums:
        r = tx(n)
        history.append(r)
        added.append(r)

    pattern = detect_pattern()
    pred = predict()

    await update.message.reply_text(f"""
📥 Nhận: {''.join(added)}
📊 History (30): {''.join(history[-30:])}

📈 Nhận diện: {pattern}

{pred}
""")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history.clear()
    await update.message.reply_text("♻️ Reset xong")

# ===== RUN =====
def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT, handle))

    print("🔥 BOT PRO ĐANG CHẠY...")
    app.run_polling()

if __name__ == "__main__":
    run()
