import os
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

history = []

def classify(x):
    return "T" if int(x) >= 11 else "X"

# 🔥 tìm pattern toàn bộ lịch sử
def find_patterns(seq, size=3):
    patterns = []
    for i in range(len(seq) - size):
        pattern = tuple(seq[i:i+size])
        next_val = seq[i+size]
        patterns.append((pattern, next_val))
    return patterns

def analyze():
    if len(history) < 10:
        return "❌ Chưa đủ dữ liệu (>=10)"

    seq = [classify(x) for x in history]

    # 🔥 lấy pattern 3 và 4
    patterns3 = find_patterns(seq, 3)
    patterns4 = find_patterns(seq, 4)

    current3 = tuple(seq[-3:])
    current4 = tuple(seq[-4:])

    vote = []

    # 🔥 quét toàn bộ lịch sử
    for p, nxt in patterns3:
        if p == current3:
            vote.append(nxt)

    for p, nxt in patterns4:
        if p == current4:
            vote.append(nxt)

    if not vote:
        return "⚠️ Không có pattern mạnh (cầu nhiễu)"

    count = Counter(vote)

    pred = count.most_common(1)[0][0]
    strength = count[pred]

    # 🔥 phát hiện cầu bẫy
    trap = False
    if len(seq) > 5:
        if seq[-1] != seq[-2] and seq[-2] != seq[-3]:
            trap = True

    return f"""
📊 AI TX PRO MAX

Lịch sử: {len(history)} ván

Chuỗi gần:
{' '.join(seq[-15:])}

Pattern match: {len(vote)}
Độ mạnh: {strength}

Dự đoán: {'🔥 TÀI' if pred=='T' else '🔥 XỈU'}

{"⚠️ CẢNH BÁO CẦU BẪY" if trap else "✅ Cầu ổn định"}
"""

# 🔥 reset
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global history
    history = []
    await update.message.reply_text("♻️ Đã reset lịch sử")

# 🔥 start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI TX PRO MAX\n\n"
        "Nhập:\n"
        "12-13-14 hoặc 12\n\n"
        "Lệnh:\n/reset để xóa lịch sử"
    )

# 🔥 nhận data
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global history
    text = update.message.text.strip()

    try:
        nums = text.split("-")
        for n in nums:
            if n:
                history.append(int(n))

        result = analyze()
        await update.message.reply_text(result)

    except:
        await update.message.reply_text("❌ Sai định dạng")

TOKEN = os.getenv("BOT_TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("reset", reset))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("🔥 AI TX PRO MAX RUNNING")

app.run_polling()
