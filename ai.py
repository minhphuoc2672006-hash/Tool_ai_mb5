import threading
import time

from crawler import start_crawler
from bot import run_bot

print("🚀 TOOL AI MB5 STARTING")


# ======================
# CRAWLER
# ======================

def run_crawler():

    print("Starting crawler...")

    try:
        start_crawler()

        while True:
            time.sleep(60)

    except Exception as e:
        print("Crawler error:", e)


# ======================
# TELEGRAM BOT
# ======================

def run_telegram():

    print("Starting telegram bot...")

    try:
        run_bot()

    except Exception as e:
        print("Bot error:", e)


# ======================
# MAIN
# ======================

if __name__ == "__main__":

    crawler_thread = threading.Thread(target=run_crawler)
    crawler_thread.daemon = True
    crawler_thread.start()

    telegram_thread = threading.Thread(target=run_telegram)
    telegram_thread.daemon = True
    telegram_thread.start()

    # giữ container chạy
    while True:
        time.sleep(60)
