import threading
import time

from crawler import start_crawler
from bot import run_bot

print("🚀 TOOL AI MB5 STARTING")


# =====================
# START CRAWLER
# =====================

def start_crawler_thread():
    try:
        print("Starting crawler...")
        start_crawler()

        while True:
            time.sleep(60)

    except Exception as e:
        print("Crawler error:", e)


# =====================
# START TELEGRAM BOT
# =====================

def start_bot_thread():
    try:
        print("Starting telegram bot...")
        run_bot()

    except Exception as e:
        print("Bot error:", e)


# =====================
# MAIN
# =====================

if __name__ == "__main__":

    crawler_thread = threading.Thread(target=start_crawler_thread)
    crawler_thread.daemon = True
    crawler_thread.start()

    start_bot_thread()
