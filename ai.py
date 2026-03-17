import threading
import time

from bot import run_bot
from crawler import start_crawler

print("🚀 TOOL AI MB5 STARTING")

def crawler_loop():

    print("Starting crawler...")

    while True:
        start_crawler()
        time.sleep(10)

if __name__ == "__main__":

    t = threading.Thread(target=crawler_loop)
    t.daemon = True
    t.start()

    run_bot()
