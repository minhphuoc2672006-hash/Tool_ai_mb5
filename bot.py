import os
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

import time
import requests
import re
from playwright.sync_api import sync_playwright

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

URL = "https://web.xvip36.win"

history = []
last_result = ""

def send(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("❌ Lỗi gửi Telegram")

def classify(total):
    return "TÀI" if total >= 11 else "XỈU"

def analyze():
    if len(history) < 6:
        return "❌ Chưa đủ dữ liệu"

    last = history[-6:]
    t = sum(1 for x in last if x >= 11)
    x = 6 - t

    if t > x:
        return "📊 Nghiêng TÀI"
    elif x > t:
        return "📊 Nghiêng XỈU"
    else:
        return "⚖️ Cân"

def run():
    global last_result

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        page = browser.new_page()

        print("🔥 BOT START")

        page.goto(URL, timeout=60000)
        page.wait_for_timeout(5000)

        while True:
            try:
                content = page.content()

                match = re.search(r'([1-6])-([1-6])-([1-6])', content)

                if match:
                    result = match.group(0)

                    if result != last_result:
                        last_result = result

                        dice = list(map(int, result.split("-")))
                        total = sum(dice)

                        history.append(total)

                        msg = f"""
🎲 {result}
👉 {total} ({classify(total)})
📦 {len(history)} ván
"""

                        send(msg + "\n" + analyze())

                time.sleep(2)

            except Exception as e:
                print("❌ Lỗi:", e)
                time.sleep(5)

run()
