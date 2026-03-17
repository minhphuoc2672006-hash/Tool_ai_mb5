import threading
import time

from crawler import start_crawler
from bot import run_bot

print("🚀 TOOL AI MB5 STARTING")


# =====================
# CRAWLER THREAD
# =====================

def crawler():

    try:
        print("Starting crawler...")

        start_crawler()

        while True:
            time.sleep(60)

    except Exception as e:
        print("Crawler error:", e)


# =====================
# MAIN
# =====================

if __name__ == "__main__":

    t = threading.Thread(target=crawler)
    t.daemon = True
    t.start()

    print("Starting telegram bot...")

    run_bot()
