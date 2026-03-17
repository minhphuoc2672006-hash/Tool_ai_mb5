import threading
from bot import run_bot
from crawler import start_crawler

print("🚀 TOOL AI MB5 STARTING")

def start_all():
    # chạy crawler ở thread riêng
    t = threading.Thread(target=start_crawler)
    t.daemon = True
    t.start()

    # chạy bot (main thread)
    run_bot()

if __name__ == "__main__":
    start_all()
