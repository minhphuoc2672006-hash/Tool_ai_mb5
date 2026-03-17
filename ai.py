import threading
import time

from crawler import start_crawler
from bot import run_bot

print("🚀 TOOL AI MB5 STARTING")


def crawler_thread():
    print("Starting crawler...")
    start_crawler()

    while True:
        time.sleep(60)


if __name__ == "__main__":

    t = threading.Thread(target=crawler_thread)
    t.daemon = True
    t.start()

    run_bot()
