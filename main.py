#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import re
from collections import Counter
from typing import List, Optional, Tuple

import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
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

DATA_SOURCE = os.getenv("DATA_SOURCE", "url").strip().lower()  # url hoặc file
DATA_URL = os.getenv(
    "DATA_URL",
    "https://raw.githubusercontent.com/USERNAME/REPO/main/data.txt"
).strip()
DATA_FILE = os.getenv("DATA_FILE", "data.txt").strip()
STATE_FILE = os.getenv("STATE_FILE", "state.json").strip()

MAX_MISMATCHES = int(os.getenv("MAX_MISMATCHES", "1"))
SOFT_WEIGHT = float(os.getenv("SOFT_WEIGHT", "0.6"))
MIN_SUPPORT_FOR_CHOT = int(os.getenv("MIN_SUPPORT_FOR_CHOT", "3"))

# =========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BIG_DATA: List[str] = []
HISTORY: List[str] = []

# =========================================
# UI
# =========================================

def menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📌 Dashboard"), KeyboardButton("➕ Nhập dữ liệu")],
        [KeyboardButton("📊 Thống kê"), KeyboardButton("🔄 Train")],
        [KeyboardButton("🧹 Reset"), KeyboardButton("🔁 Reload data")],
        [KeyboardButton("ℹ️ Hướng dẫn")],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )

def is_admin(uid: int) -> bool:
    return (not ADMIN_IDS) or (uid in ADMIN_IDS)

# =========================================
# DATA CONVERSION
# =========================================

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

def extract_tx(raw: str) -> List[str]:
    """
    Đọc được:
    - T X T X
    - 12-13-8-9
    - 12 13 8 9
    - 12,13,8,9
    - xuống dòng, tab, dấu gạch
    """
    if not raw:
        return []

    raw = raw.upper().replace("-", " ").replace(",", " ")
    tokens = re.findall(r"[TX]|\d+", raw)

    out: List[str] = []
    for tok in tokens:
        if tok in ("T", "X"):
            out.append(tok)
        else:
            v = tx(int(tok))
            if v is not None:
                out.append(v)
    return out

def parse_input(text: str) -> List[str]:
    """
    Parse dữ liệu người dùng nhập vào bot.
    Chấp nhận:
    - T X X T
    - 12-13-8
    - 12 13 8
    """
    if not text:
        return []

    text = text.upper().replace("-", " ").replace(",", " ")
    tokens = re.findall(r"[TX]|\d+", text)

    out: List[str] = []
    for tok in tokens:
        if tok in ("T", "X"):
            out.append(tok)
        else:
            v = tx(int(tok))
            if v is not None:
                out.append(v)
    return out

# =========================================
# LOAD / SAVE
# =========================================

def load_data() -> None:
    global BIG_DATA
    raw = ""
    try:
        if DATA_SOURCE == "url":
            res = requests.get(DATA_URL, timeout=20)
            res.raise_for_status()
            raw = res.text
        else:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = f.read()

        BIG_DATA = extract_tx(raw)
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
# SCAN / MATCH
# =========================================

def scan_hits(data: List[str], pattern: List[str], max_mismatches: int = 0) -> List[str]:
    """
    Trả về danh sách kết quả ngay sau pattern.
    max_mismatches = 0: khớp chính xác
    max_mismatches = 1: khớp gần
    """
    hits: List[str] = []
    n = len(pattern)

    if n == 0 or len(data) < n + 1:
        return hits

    for i in range(len(data) - n):
        window = data[i:i + n]
        mismatches = sum(1 for a, b in zip(window, pattern) if a != b)
        if mismatches <= max_mismatches:
            hits.append(data[i + n])

    return hits

def weighted_counts(results: List[Tuple[str, float]]) -> Tuple[Counter, float]:
    c = Counter()
    total_weight = 0.0
    for result, weight in results:
        c[result] += weight
        total_weight += weight
    return c, total_weight

# =========================================
# ANALYSIS
# =========================================

def fallback_baseline() -> Tuple[Counter, float]:
    """
    Thống kê nền khi pattern chưa đủ khớp.
    Ưu tiên HISTORY gần nhất, nếu ít thì dùng BIG_DATA.
    """
    source = HISTORY[-30:] if len(HISTORY) >= 6 else BIG_DATA[-200:]
    if not source:
        return Counter(), 0.0

    c = Counter(source)
    total = float(sum(c.values()))
    return c, total

def analyze_multi() -> str:
    if len(HISTORY) < 3:
        return "❌ Chưa đủ dữ liệu"

    depths = [3, 4, 5]
    text = "🧠 PHÂN TÍCH\n\n"

    final_pool: List[Tuple[str, float]] = []

    for d in depths:
        if len(HISTORY) < d:
            continue

        pattern = HISTORY[-d:]
        pattern_text = "".join(pattern)

        # Khớp trong BIG_DATA
        exact_hits = scan_hits(BIG_DATA, pattern, max_mismatches=0)

        # Khớp trong HISTORY cũ, không lấy phần đang phân tích
        history_prev = HISTORY[:-d] if len(HISTORY) > d else []
        exact_hits += scan_hits(history_prev, pattern, max_mismatches=0)

        # Nếu ít quá thì thử khớp gần
        soft_hits: List[str] = []
        if len(exact_hits) < 2:
            soft_hits = scan_hits(BIG_DATA, pattern, max_mismatches=MAX_MISMATCHES)
            soft_hits += scan_hits(history_prev, pattern, max_mismatches=MAX_MISMATCHES)

        depth_pool: List[Tuple[str, float]] = []
        for r in exact_hits:
            depth_pool.append((r, 1.0))
        for r in soft_hits:
            depth_pool.append((r, SOFT_WEIGHT))

        if depth_pool:
            c, total_w = weighted_counts(depth_pool)
            t = c.get("T", 0.0)
            x = c.get("X", 0.0)

            tp = (t * 100 / total_w) if total_w else 0.0
            xp = (x * 100 / total_w) if total_w else 0.0

            text += f"🔹 Cầu {d}: {pattern_text}\n"
            text += f"Khớp: {len(exact_hits)} chính xác, {len(soft_hits)} gần\n"
            text += f"T: {round(tp, 1)}% | X: {round(xp, 1)}% | Mẫu: {round(total_w, 1)}\n\n"

            if total_w >= MIN_SUPPORT_FOR_CHOT:
                final_pool += depth_pool
        else:
            text += f"🔹 Cầu {d}: {pattern_text}\n"
            text += "Không có khớp chính xác, sẽ dùng nền nếu cần\n\n"

    if not final_pool:
        base_counts, base_total = fallback_baseline()
        if base_total <= 0:
            text += "⛔ Chưa đủ dữ liệu để chốt"
            return text

        t = base_counts.get("T", 0)
        x = base_counts.get("X", 0)
        tp = (t * 100 / base_total) if base_total else 0.0
        xp = (x * 100 / base_total) if base_total else 0.0

        text += "📌 Nền dữ liệu\n"
        text += f"T: {round(tp, 1)}% | X: {round(xp, 1)}% | Mẫu: {int(base_total)}\n\n"

        if abs(tp - xp) < 3:
            text += "⛔ BỎ QUA (nền cân kèo)"
            return text

        if tp > xp:
            text += f"⚠️ TÀI (nền) ({round(tp, 1)}%)"
        else:
            text += f"⚠️ XỈU (nền) ({round(xp, 1)}%)"
        return text

    final_counts, final_weight = weighted_counts(final_pool)
    t = final_counts.get("T", 0.0)
    x = final_counts.get("X", 0.0)

    tp = (t * 100 / final_weight) if final_weight else 0.0
    xp = (x * 100 / final_weight) if final_weight else 0.0

    if abs(tp - xp) < 3:
        text += "⛔ BỎ QUA (cân kèo)"
        return text

    if tp > xp:
        confidence = tp
        if confidence >= 60:
            text += f"🔥 CHỐT TÀI ({round(confidence, 1)}%)"
        else:
            text += f"⚠️ TÀI (yếu) ({round(confidence, 1)}%)"
    else:
        confidence = xp
        if confidence >= 60:
            text += f"🔥 CHỐT XỈU ({round(confidence, 1)}%)"
        else:
            text += f"⚠️ XỈU (yếu) ({round(confidence, 1)}%)"

    return text

# =========================================
# TEXT BUILDERS
# =========================================

def dashboard_text() -> str:
    history_preview = " ".join(HISTORY[-20:]) if HISTORY else "(trống)"
    return (
        "📌 DASHBOARD\n\n"
        f"📚 BIG_DATA: {len(BIG_DATA)}\n"
        f"🧠 HISTORY: {len(HISTORY)}\n"
        f"🔎 20 kết quả gần nhất: {history_preview}\n\n"
        f"{analyze_multi()}"
    )

def stats_text() -> str:
    total = len(HISTORY)
    c = Counter(HISTORY)
    t = c.get("T", 0)
    x = c.get("X", 0)

    tp = (t * 100 / total) if total else 0.0
    xp = (x * 100 / total) if total else 0.0

    return (
        "📊 THỐNG KÊ\n\n"
        f"📥 Tổng lịch sử nhập: {total}\n"
        f"🔥 T: {t} ({round(tp, 1)}%)\n"
        f"🧊 X: {x} ({round(xp, 1)}%)\n"
        f"📚 BIG_DATA: {len(BIG_DATA)}\n"
    )

def guide_text() -> str:
    return (
        "ℹ️ HƯỚNG DẪN\n\n"
        "• Gửi số từ 3 đến 18 để bot lưu vào HISTORY.\n"
        "• 3–10 = X, 11–18 = T.\n"
        "• /reset chỉ xóa HISTORY, không đụng BIG_DATA.\n"
        "• BIG_DATA là dữ liệu gốc từ data.txt hoặc URL.\n"
        "• Bot đọc được cả T/X và số, kể cả có dấu -, dấu phẩy, hoặc xuống dòng.\n"
    )

def input_hint_text() -> str:
    return (
        "➕ NHẬP DỮ LIỆU\n\n"
        "Gửi từng kết quả, hoặc gửi cả chuỗi như:\n"
        "14-14-5-11-7-8\n\n"
        "Bot sẽ tự lưu vào HISTORY và phân tích tiếp."
    )

# =========================================
# HANDLERS
# =========================================

async def send_menu(update: Update, text: str) -> None:
    if update.message:
        await update.message.reply_text(text, reply_markup=menu_keyboard())

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    await send_menu(update, "Bot đã sẵn sàng 🔥")

async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    HISTORY.clear()
    save()
    await send_menu(update, "✅ Reset xong phần lịch sử nhập tay. BIG_DATA vẫn giữ nguyên.")

async def reload_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    load_data()
    await send_menu(update, f"🔄 Đã tải lại BIG_DATA: {len(BIG_DATA)}")

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not update.message:
        return

    text = update.message.text or ""
    stripped = text.strip()

    # Nút giao diện
    if stripped == "📌 Dashboard":
        await send_menu(update, dashboard_text())
        return

    if stripped == "📊 Thống kê":
        await send_menu(update, stats_text())
        return

    if stripped == "🔄 Train":
        await send_menu(update, analyze_multi())
        return

    if stripped == "🧹 Reset":
        HISTORY.clear()
        save()
        await send_menu(update, "✅ Reset xong phần lịch sử nhập tay. BIG_DATA vẫn giữ nguyên.")
        return

    if stripped == "ℹ️ Hướng dẫn":
        await send_menu(update, guide_text())
        return

    if stripped == "➕ Nhập dữ liệu":
        await send_menu(update, input_hint_text())
        return

    if stripped == "🔁 Reload data":
        await reload_data(update, ctx)
        return

    # Xử lý dữ liệu người dùng nhập vào
    vals = parse_input(text)
    if not vals:
        return

    added = []
    ignored = []

    for v in vals:
        if v in ("T", "X"):
            HISTORY.append(v)
            added.append(v)
        else:
            ignored.append(v)

    if not added:
        await send_menu(
            update,
            f"⚠️ Không có giá trị hợp lệ.\nDữ liệu nhận: {vals}"
        )
        return

    save()

    result = analyze_multi()
    reply = (
        f"📥 Nhận: {vals}\n"
        f"➡️ {' '.join(added)}"
    )

    if ignored:
        reply += f"\n⚠️ Bỏ qua: {ignored}"

    reply += f"\n\n{result}"

    await send_menu(update, reply)

# =========================================
# MAIN
# =========================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Thiếu BOT_TOKEN trong biến môi trường")

    load()
    load_data()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("reloaddata", reload_data))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
