#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import html
import json
import os
import random
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters


# =========================
# ENV
# =========================
def load_env():
    if not Path(".env").exists():
        return

    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


load_env()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATA_FILE = Path("data.json")

if not BOT_TOKEN or not ADMIN_ID:
    raise RuntimeError("Thiếu BOT_TOKEN hoặc ADMIN_ID")


# =========================
# CONFIG
# =========================
HISTORY_LIMIT = 5000


# =========================
# HELPERS
# =========================
def esc(x): return html.escape(str(x))


def normalize(text):
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn").upper()


def parse_pattern(text):
    m = re.search(r"(\d+)\s*-\s*(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def parse_input(text):
    t = normalize(text)

    result = None
    if "TAI" in t:
        result = "TAI"
    elif "XIU" in t:
        result = "XIU"

    number = None
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        number = int(m.group(1))

    pattern = parse_pattern(t)

    return result, number, pattern


def matches_pattern(seq, x, y):
    if len(seq) != x + y:
        return False
    a = seq[:x]
    b = seq[x:]
    return len(set(a)) == 1 and len(set(b)) == 1 and a[0] != b[0]


# =========================
# STATE
# =========================
@dataclass
class Brain:
    history: List[Dict[str, Any]] = field(default_factory=list)

    def save(self):
        DATA_FILE.write_text(json.dumps(self.history, ensure_ascii=False))

    def load(self):
        if DATA_FILE.exists():
            self.history = json.loads(DATA_FILE.read_text())

    def reset(self):
        self.history = []
        self.save()

    def add(self, result, number):
        self.history.append({"result": result, "number": number})
        self.history = self.history[-HISTORY_LIMIT:]
        self.save()

    def analyze(self, p):
        x, y = p
        res = [h["result"] for h in self.history]

        seen = tai = xiu = 0

        for i in range(len(res) - (x+y)):
            if matches_pattern(res[i:i+x+y], x, y):
                seen += 1
                if res[i+x+y] == "TAI":
                    tai += 1
                else:
                    xiu += 1

        return f"{x}-{y}: seen={seen}, Tài={tai}, Xỉu={xiu}"

    def analyze_number(self, number, p):
        x, y = p
        seen = tai = xiu = 0

        for i in range(len(self.history) - (x+y)):
            window = self.history[i:i+x+y]
            seq = [w["result"] for w in window]

            if not matches_pattern(seq, x, y):
                continue

            if window[-1]["number"] != number:
                continue

            seen += 1
            nxt = self.history[i+x+y]["result"]

            if nxt == "TAI":
                tai += 1
            else:
                xiu += 1

        return f"Số {number} + {x}-{y}: seen={seen}, Tài={tai}, Xỉu={xiu}"


brain = Brain()
brain.load()
LOCK = asyncio.Lock()


# =========================
# AUTO RANDOM
# =========================
async def auto_random():
    while True:
        async with LOCK:
            for _ in range(10000):
                brain.add(
                    random.choice(["TAI", "XIU"]),
                    random.randint(3, 18)
                )
        print("Random +10000")
        await asyncio.sleep(60)


# =========================
# COMMANDS
# =========================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    msg = (
        "📖 HƯỚNG DẪN\n"
        "━━━━━━━━━━━━━━\n"
        "Tài / Xỉu → lưu\n"
        "Tài 11 → lưu + số\n"
        "2-1 → xem cầu\n"
        "Tài 11 cầu 2-1 → phân tích sâu\n"
        "/status → xem tổng\n"
        "/reset → xóa dữ liệu\n"
    )
    await update.message.reply_text(msg)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Tổng: {len(brain.history)}")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brain.reset()
    await update.message.reply_text("Đã reset")


# =========================
# HANDLER
# =========================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    text = update.message.text

    async with LOCK:
        result, number, pattern = parse_input(text)

        if result:
            brain.add(result, number)

        if number and pattern:
            msg = brain.analyze_number(number, pattern)
        elif pattern:
            msg = brain.analyze(pattern)
        else:
            msg = f"Đã lưu {result} {number}" if result else "Không hiểu"

    await update.message.reply_text(msg)


# =========================
# MAIN
# =========================
async def post_init(app):
    app.create_task(auto_random())


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT, handle))

    print("Bot chạy + auto random...")
    app.run_polling()


if __name__ == "__main__":
    main()
