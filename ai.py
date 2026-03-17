import threading
from bot import run_bot

def start_all():
    print("🚀 START TOOL AI MB5")

    t = threading.Thread(target=run_bot)
    t.start()

    print("✅ BOT RUNNING")

if __name__ == "__main__":
    start_all()
