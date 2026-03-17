import os
import time
import re
import requests
from collections import Counter

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

history = []
last_result = ""

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def classify(total):
    return "T" if total >= 11 else "X"

def analyze():
    if len(history) < 6:
        return "❌ Chưa đủ dữ liệu"

    seq = [classify(x) for x in history]

    patterns = {}
    for i in range(len(seq) - 3):
        key = tuple(seq[i:i+3])
        nxt = seq[i+3]
        patterns.setdefault(key, []).append(nxt)

    current = tuple(seq[-3:])
    votes = patterns.get(current, [])

    if not votes:
        return "⚠️ Cầu nhiễu"

    count = Counter(votes)
    pred = count.most_common(1)[0][0]

    return f"📊 Dự đoán: {'🔥 TÀI' if pred=='T' else '🔥 XỈU'}"

print("🔥 BOT NON-SELENIUM START")

while True:
    try:
        # 🔥 Lấy HTML trực tiếp
        html = requests.get("https://web.xvip36.win").text

        match = re.search(r'([1-6])-([1-6])-([1-6])', html)

        if match:
            result = match.group(0)

            if result != last_result:
                last_result = result

                dice = list(map(int, result.split("-")))
                total = sum(dice)
                tx = classify(total)

                history.append(total)

                msg = f"""
🎲 {result}
👉 {total} ({tx})
📦 {len(history)} ván
"""

                send(msg + "\n" + analyze())

        time.sleep(3)

    except Exception as e:
        print("Lỗi:", e)
        time.sleep(5)
