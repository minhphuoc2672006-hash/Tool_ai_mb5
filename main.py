#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import re
from collections import Counter
from typing import List, Optional

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Ví dụ: ADMIN_IDS="123456789,987654321"
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [
    int(x.strip())
    for x in ADMIN_IDS_RAW.split(",")
    if x.strip().isdigit()
]

DATA_SOURCE = os.getenv("DATA_SOURCE", "url").strip().lower()  # "url" hoặc "file"
DATA_URL = os.getenv(
    "DATA_URL",
    "https://raw.githubusercontent.com/USERNAME/REPO/main/data.txt"
).strip()
DATA_FILE = os.getenv("DATA_FILE", "data.txt").strip()

STATE_FILE = os.getenv("STATE_FILE", "state.json").strip()

# =========================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BIG_DATA: List[str] = []
HISTORY: List[str] = []

# =========================================

def is_admin(uid: int) -> bool:
    return (not ADMIN_IDS) or (uid in ADMIN_IDS)

def tx(n: int) -> Optional[str]:
    """
    Quy ước:
    - 3 đến 10  => X
    - 11 đến 18 => T
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None

    if 3 <= n <= 10:
        return "X"
    if 11 <= n <= 18:
        return "T"
    return None

def parse(text: str) -> List[int]:
    if not text:
        return []
    return [int(x) for x in re.findall(r"\d+", text)]

# =========================================

def load_data() -> None:
    global BIG_DATA

    raw = ""
    try:
        if DATA_SOURCE == "url":
            res = requests.get(DATA_URL, timeout=15)
            res.raise_for_status()
            raw = res.text
        else:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = f.read()

        nums = [int(x) for x in re.findall(r"\d+", raw)]
        BIG_DATA = []
        for n in nums:
            v = tx(n)
            if v is not None:
                BIG_DATA.append(v)

        logging.info("Loaded BIG_DATA: %d items", len(BIG_DATA))

    except Exception as e:
        logging.exception("load_data failed: %s", e)
        BIG_DATA = []

def save() -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"h": HISTORY}, f, ensure_ascii=False)
    except Exception as e:
        logging.exception("save failed: %s", e)

def load() -> None:
    global HISTORY
    if not os.path.exists(STATE_FILE):
        HISTORY = []
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        h = data.get("h", [])
        if isinstance(h, list):
            HISTORY = [x for x in h if x in ("T", "X")]
        else:
            HISTORY = []
    except Exception as e:
        logging.exception("load failed: %s", e)
        HISTORY = []

# =========================================

def scan(pattern: List[str]) -> List[str]:
    """
    Tìm các lần pattern xuất hiện trong BIG_DATA,
    sau đó lấy phần tử ngay sau pattern.
    """
    res: List[str] = []
    n = len(pattern)

    if n == 0 or len(BIG_DATA) < n + 1:
        return res

    # SỬA LỖI QUAN TRỌNG: phải là len(BIG_DATA) - n + 1
    for i in range(len(BIG_DATA) - n + 1):
        if BIG_DATA[i:i + n] == pattern:
            res.append(BIG_DATA[i + n])

    return res

# =========================================

def analyze_multi() -> str:
    if len(HISTORY) < 3:
        return "❌ Chưa đủ dữ liệu"

    depths = [3, 4, 5]
    scores = {"T": 0, "X": 0}
    total_support = 0

    text = "🧠 PHÂN TÍCH\n\n"

    for d in depths:
        if len(HISTORY) < d:
            continue

        p = HISTORY[-d:]
        res = scan(p)

        if not res:
            text += f"🔹 Cầu {d}: {''.join(p)}\n"
            text += "Không có dữ liệu khớp\n\n"
            continue

        c = Counter(res)
        total = sum(c.values())
        t = c.get("T", 0)
        x = c.get("X", 0)

        tp = (t * 100 / total) if total else 0
        xp = (x * 100 / total) if total else 0

        text += f"🔹 Cầu {d}: {''.join(p)}\n"
        text += f"T: {round(tp, 1)}% | X: {round(xp, 1)}% | Mẫu: {total}\n\n"

        # Chỉ lấy cầu đủ mẫu để tránh nhiễu
        if total >= 10:
            scores["T"] += t
            scores["X"] += x
            total_support += total

    if total_support == 0:
        text += "⛔ Không đủ dữ liệu để chốt"
        return text

    diff = abs(scores["T"] - scores["X"])
    if diff == 0:
        text += "⛔ BỎ QUA (cân kèo)"
        return text

    # Có thể chỉnh ngưỡng này nếu bạn muốn chặt hơn
    if diff < 3:
        text += "⛔ BỎ QUA (chênh lệch quá nhỏ)"
        return text

    if scores["T"] > scores["X"]:
        confidence = scores["T"] / max(scores["T"] + scores["X"], 1) * 100
        if confidence >= 60:
            text += f"🔥 CHỐT TÀI ({round(confidence, 1)}%)"
        else:
            text += f"⚠️ TÀI (yếu) ({round(confidence, 1)}%)"
    else:
        confidence = scores["X"] / max(scores["T"] + scores["X"], 1) * 100
        if confidence >= 60:
            text += f"🔥 CHỐT XỈU ({round(confidence, 1)}%)"
        else:
            text += f"⚠️ XỈU (yếu) ({round(confidence, 1)}%)"

    return text

# =========================================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("Bot đã sẵn sàng 🔥")

async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    HISTORY.clear()
    save()
    await update.message.reply_text("✅ Reset xong (không ảnh hưởng data gốc)")

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    text = update.message.text or ""
    nums = parse(text)
    if not nums:
        return

    added = []
    ignored = []

    for n in nums:
        v = tx(n)
        if v is None:
            ignored.append(n)
            continue
        HISTORY.append(v)
        added.append(v)

    if not added:
        await update.message.reply_text(
            f"⚠️ Không có số hợp lệ trong phạm vi 3–18.\n"
            f"Dữ liệu nhận: {nums}"
        )
        return

    save()
    result = analyze_multi()

    reply = (
        f"📥 Nhận: {nums}\n"
        f"➡️ {' '.join(added)}"
    )

    if ignored:
        reply += f"\n⚠️ Bỏ qua: {ignored}"

    reply += f"\n\n{result}"

    await update.message.reply_text(reply)

# =========================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Thiếu BOT_TOKEN trong biến môi trường")

    load()
    load_data()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
