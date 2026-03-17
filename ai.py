import threading
import time

from crawler import start_crawler
from bot import run_bot

print("🚀 TOOL AI MB5 STARTING")


def run_crawler():

    try:
        print("Starting crawler...")

        start_crawler()

        while True:
            time.sleep(60)

    except Exception as e:

        print("Crawler error:", e)


if __name__ == "__main__":

    crawler_thread = threading.Thread(target=run_crawler)
    crawler_thread.daemon = True
    crawler_thread.start()

    print("Starting telegram bot...")

    run_bot()
