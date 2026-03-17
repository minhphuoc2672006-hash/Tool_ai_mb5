import threading
import time

from crawler import start_crawler
from bot import run_bot

print("🚀 Starting TOOL AI MB5")


# ======================
# RUN CRAWLER
# ======================

def crawler_thread():

    print("Starting crawler...")

    try:
        start_crawler()

        while True:
            time.sleep(60)

    except Exception as e:
        print("Crawler error:", e)


# ======================
# MAIN
# ======================

if __name__ == "__main__":

    t = threading.Thread(target=crawler_thread)
    t.daemon = True
    t.start()

    print("Starting telegram bot...")

    run_bot()
