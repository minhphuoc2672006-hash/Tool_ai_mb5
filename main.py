#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import logging
from typing import List

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_FILE = "history.db"

THRESHOLD = 11
LOW_LABEL = "Xỉu"
HIGH_LABEL = "Tài"

ANALYSIS_WINDOW = 5000   # chỉ phân tích500kết quả gần

logging.basicConfig(level=logging.INFO)

# ================= DB =================
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    with db() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            value INTEGER,
            label TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            chat_id INTEGER PRIMARY KEY,
            ready INTEGER DEFAULT 0
        )
        """)

# ================= PARSE =================
def parse_numbers(text: str) -> List[int]:
    nums = re.findall(r"\d+", text)
    return [int(x) for x in nums]

def classify(n: int) -> str:
    return HIGH_LABEL if n >= THRESHOLD else LOW_LABEL

# ================= CORE =================
def save_bulk(chat_id: int, nums: List[int]):
    with db() as c:
        c.executemany(
            "INSERT INTO history (chat_id, value, label) VALUES (?, ?, ?)",
            [(chat_id, n, classify(n)) for n in nums]
        )
        c.execute(
            "INSERT OR IGNORE INTO meta (chat_id, ready) VALUES (?, 0)",
            (chat_id,)
        )

def save_one(chat_id: int, n: int):
    with db() as c:
        c.execute(
            "INSERT INTO history (chat_id, value, label) VALUES (?, ?, ?)",
            (chat_id, n, classify(n))
        )

def get_recent(chat_id: int) -> List[str]:
    with db() as c:
        rows = c.execute(
            "SELECT label FROM history WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, ANALYSIS_WINDOW)
        ).fetchall()
    return [r[0] for r in rows][::-1]

def is_ready(chat_id: int) -> bool:
    with db() as c:
        r = c.execute("SELECT ready FROM meta WHERE chat_id=?", (chat_id,)).fetchone()
        return r and r[0] == 1

def set_ready(chat_id: int):
    with db() as c:
        c.execute(
            "INSERT INTO meta (chat_id, ready) VALUES (?, 1) "
            "ON CONFLICT(chat_id) DO UPDATE SET ready=1",
            (chat_id,)
        )

# ================= ANALYSIS =================
def simple_predict(labels: List[str]):
    if len(labels) < 10:
        return "Chưa đủ dữ liệu"

    tai = labels.count(HIGH_LABEL)
    xiu = labels.count(LOW_LABEL)

    total = len(labels)
    ptai = tai / total
    pxiu = xiu / total

    if ptai > pxiu:
        return f"Dự đoán: Tài ({ptai:.2%})"
    else:
        return f"Dự đoán: Xỉu ({pxiu:.2%})"

# ================= HANDLER =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    nums = parse_numbers(text)

    if not nums:
        await update.message.reply_text("Không có số hợp lệ")
        return

    # 👉 Nếu nhập nhiều (bulk)
    if len(nums) > 1:
        save_bulk(chat_id, nums)
        await update.message.reply_text(
            f"✅ Đã lưu {len(nums)} kết quả\n👉 Nhập 1 kết quả mới để bắt đầu phân tích"
        )
        return

    # 👉 Nếu nhập 1 số
    n = nums[0]
    save_one(chat_id, n)

    # nếu chưa ready thì bật
    if not is_ready(chat_id):
        set_ready(chat_id)

    labels = get_recent(chat_id)
    result = simple_predict(labels)

    await update.message.reply_text(
        f"📥 Nhận: {n} ({classify(n)})\n{result}"
    )

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()

if __name__ == "__main__":
    main()
