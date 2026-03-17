import os
import time
import re
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from collections import Counter

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

history = []
last_result = ""

# ================= TELE =================
def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= LOGIC =================
def classify(total):
    return "T" if total >= 11 else "X"

def analyze():
    if len(history) < 6:
        return "❌ Chưa đủ dữ liệu"

    seq = [classify(x) for x in history]

    # pattern 3
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

    return f"""
📊 AI TX PRO MAX
Chuỗi gần: {' '.join(seq[-10:])}
Dự đoán: {'🔥 TÀI' if pred=='T' else '🔥 XỈU'}
"""

# ================= CHROME =================
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(options=chrome_options)
driver.get("https://web.xvip36.win")

print("🔥 BOT PRO MAX ĐANG CHẠY...")

# ================= LOAD LỊCH SỬ BAN ĐẦU =================
time.sleep(5)
text = driver.find_element("tag name", "body").text
matches = re.findall(r'([1-6])\s*-\s*([1-6])\s*-\s*([1-6])', text)

for m in matches:
    dice = list(map(int, m))
    total = sum(dice)
    history.append(total)

print("🔥 Đã load lịch sử:", history)

# ================= LOOP =================
while True:
    try:
        text = driver.find_element("tag name", "body").text

        match = re.search(r'([1-6])\s*-\s*([1-6])\s*-\s*([1-6])', text)

        if match:
            result = match.group(0)

            if result != last_result:
                last_result = result

                dice = list(map(int, result.split("-")))
                total = sum(dice)
                tx = classify(total)

                history.append(total)

                msg = f"""
🎲 KẾT QUẢ: {result}
👉 Tổng: {total} ({tx})
📦 Tổng lịch sử: {len(history)}
"""

                ai = analyze()

                send(msg + "\n" + ai)

        time.sleep(2)

    except Exception as e:
        print("Lỗi:", e)
        time.sleep(2)
