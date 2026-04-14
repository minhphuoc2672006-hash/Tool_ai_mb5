#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
from typing import List
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_FILE = "history.db"

THRESHOLD = 11
ANALYSIS_WINDOW = 200

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

# ================= PARSE =================
def parse_numbers(text: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d+", text)]

def classify(n: int) -> str:
    return "Tài" if n >= THRESHOLD else "Xỉu"

# ================= SAVE =================
def save_bulk(chat_id, nums):
    with db() as c:
        c.executemany(
            "INSERT INTO history (chat_id, value, label) VALUES (?, ?, ?)",
            [(chat_id, n, classify(n)) for n in nums]
        )

def save_one(chat_id, n):
    with db() as c:
        c.execute(
            "INSERT INTO history (chat_id, value, label) VALUES (?, ?, ?)",
            (chat_id, n, classify(n))
        )

# ================= LOAD =================
def get_recent(chat_id):
    with db() as c:
        rows = c.execute(
            "SELECT label FROM history WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, ANALYSIS_WINDOW)
        ).fetchall()
    return [r[0] for r in rows][::-1]

# ================= ANALYSIS =================
def analyze(labels):
    if len(labels) < 20:
        return "Chưa đủ dữ liệu"

    last = labels[-1]

    # ===== STREAK =====
    streak = 1
    for i in range(len(labels)-2, -1, -1):
        if labels[i] == last:
            streak += 1
        else:
            break

    # ===== MARKOV =====
    trans = {"Tài": {"Tài":0,"Xỉu":0}, "Xỉu":{"Tài":0,"Xỉu":0}}
    for i in range(len(labels)-1):
        trans[labels[i]][labels[i+1]] += 1

    # ===== PATTERN =====
    pattern = {"Tài":0, "Xỉu":0}
    if len(labels) >= 6:
        seq = labels[-6:]

        # xen kẽ
        if seq[0] != seq[1] and seq[0] == seq[2]:
            pattern[labels[-2]] += 2

        # 2-2
        if seq[0] == seq[1] and seq[2] == seq[3]:
            pattern[seq[0]] += 1

    # ===== SCORE =====
    score = {"Tài":0, "Xỉu":0}

    # streak anti-bệt
    if streak >= 3:
        other = "Xỉu" if last == "Tài" else "Tài"
        score[other] += 2
    else:
        score[last] += 1

    # markov
    if trans[last]["Tài"] > trans[last]["Xỉu"]:
        score["Tài"] += 1
    else:
        score["Xỉu"] += 1

    # pattern
    score["Tài"] += pattern["Tài"]
    score["Xỉu"] += pattern["Xỉu"]

    final = "Tài" if score["Tài"] > score["Xỉu"] else "Xỉu"

    return f"""
📊 PHÂN TÍCH

Chuỗi: {last} x{streak}

Markov:
{last} → Tài: {trans[last]['Tài']}
{last} → Xỉu: {trans[last]['Xỉu']}

Pattern:
Tài: {pattern['Tài']}
Xỉu: {pattern['Xỉu']}

Score:
Tài: {score['Tài']}
Xỉu: {score['Xỉu']}

Kết quả: {final}
"""

# ================= HANDLER =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    nums = parse_numbers(update.message.text)

    if not nums:
        await update.message.reply_text("Không có số hợp lệ")
        return

    if len(nums) > 1:
        save_bulk(chat_id, nums)
        await update.message.reply_text(f"Đã lưu {len(nums)} kết quả")
        return

    n = nums[0]
    save_one(chat_id, n)

    labels = get_recent(chat_id)
    result = analyze(labels)

    await update.message.reply_text(f"Nhận: {n} ({classify(n)})\n{result}")

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()

if __name__ == "__main__":
    main()
