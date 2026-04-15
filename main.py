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
BIG_RUNS: List[Tuple[str, int]] = []
HISTORY: List[str] = []

# =========================================
# UI
# =========================================

def menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📌 Dashboard"), KeyboardButton("➕ Nhập dữ liệu")],
        [KeyboardButton("📊 Thống kê"), KeyboardButton("🔄 Train")],
        [KeyboardButton("🧩 Cụm"), KeyboardButton("🎯 Chốt cuối")],
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

def build_runs(seq: List[str]) -> List[Tuple[str, int]]:
    """
    T T X X X T  -> [('T', 2), ('X', 3), ('T', 1)]
    """
    runs: List[Tuple[str, int]] = []
    if not seq:
        return runs

    cur = seq[0]
    cnt = 1

    for s in seq[1:]:
        if s == cur:
            cnt += 1
        else:
            runs.append((cur, cnt))
            cur = s
            cnt = 1

    runs.append((cur, cnt))
    return runs

def runs_to_text(runs: List[Tuple[str, int]], limit: int = 8) -> str:
    part = runs[-limit:]
    if not part:
        return "(trống)"
    return " ".join(f"{s}({n})" for s, n in part)

# =========================================
# LOAD / SAVE
# =========================================

def load_data() -> None:
    global BIG_DATA, BIG_RUNS
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
        BIG_RUNS = build_runs(BIG_DATA)

        logging.info("Loaded BIG_DATA: %d items", len(BIG_DATA))
        logging.info("Loaded BIG_RUNS: %d runs", len(BIG_RUNS))
    except Exception as e:
        logging.exception("load_data failed: %s", e)
        BIG_DATA = []
        BIG_RUNS = []

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

def scan_run_hits(
    runs: List[Tuple[str, int]],
    pattern_runs: List[Tuple[str, int]],
    max_len_gap: int = 0
) -> List[str]:
    """
    Match theo cụm:
    [('T',2),('X',3)] sẽ đi tìm trong runs.
    Trả về symbol của run kế tiếp sau cụm match.
    """
    hits: List[str] = []
    n = len(pattern_runs)

    if n == 0 or len(runs) < n + 1:
        return hits

    for i in range(len(runs) - n):
        window = runs[i:i + n]
        ok = True

        for (s1, l1), (s2, l2) in zip(window, pattern_runs):
            if s1 != s2 or abs(l1 - l2) > max_len_gap:
                ok = False
                break

        if ok:
            hits.append(runs[i + n][0])

    return hits

def weighted_counts(results: List[Tuple[str, float]]) -> Tuple[Counter, float]:
    c = Counter()
    total_weight = 0.0
    for result, weight in results:
        c[result] += weight
        total_weight += weight
    return c, total_weight

def decision_from_counts(c: Counter, total: float) -> str:
    if total <= 0:
        return "⛔ Chưa đủ dữ liệu để chốt"

    t = c.get("T", 0.0)
    x = c.get("X", 0.0)
    tp = (t * 100 / total) if total else 0.0
    xp = (x * 100 / total) if total else 0.0

    if abs(tp - xp) < 3:
        return "⛔ BỎ QUA (cân kèo)"

    if tp > xp:
        if tp >= 60:
            return f"🔥 CHỐT TÀI ({round(tp, 1)}%)"
        return f"⚠️ TÀI (yếu) ({round(tp, 1)}%)"
    else:
        if xp >= 60:
            return f"🔥 CHỐT XỈU ({round(xp, 1)}%)"
        return f"⚠️ XỈU (yếu) ({round(xp, 1)}%)"

# =========================================
# ANALYSIS - RAW
# =========================================

def analyze_raw_section() -> Tuple[str, List[Tuple[str, float]]]:
    if len(HISTORY) < 3:
        return "🔹 CẦU THƯỜNG\n❌ Chưa đủ dữ liệu\n\n", []

    depths = [3, 4, 5]
    text = "🔹 CẦU THƯỜNG\n\n"
    final_pool: List[Tuple[str, float]] = []

    for d in depths:
        if len(HISTORY) < d:
            continue

        pattern = HISTORY[-d:]
        pattern_text = "".join(pattern)

        exact_hits = scan_hits(BIG_DATA, pattern, max_mismatches=0)

        history_prev = HISTORY[:-d] if len(HISTORY) > d else []
        exact_hits += scan_hits(history_prev, pattern, max_mismatches=0)

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

            text += f"🔸 Pattern {d}: {pattern_text}\n"
            text += f"Khớp: {len(exact_hits)} chính xác, {len(soft_hits)} gần\n"
            text += f"T: {round((t * 100 / total_w), 1)}% | X: {round((x * 100 / total_w), 1)}% | Mẫu: {round(total_w, 1)}\n"
            text += f"=> {decision_from_counts(c, total_w)}\n\n"

            if total_w >= MIN_SUPPORT_FOR_CHOT:
                final_pool += depth_pool
        else:
            text += f"🔸 Pattern {d}: {pattern_text}\n"
            text += "Không có khớp chính xác, sẽ dùng nền nếu cần\n\n"

    return text, final_pool

# =========================================
# ANALYSIS - CLUSTER
# =========================================

def analyze_cluster_section() -> Tuple[str, List[Tuple[str, float]]]:
    if len(HISTORY) < 4:
        return "🧩 PHÂN TÍCH CỤM\n❌ Chưa đủ dữ liệu cụm\n\n", []

    current_runs = build_runs(HISTORY)
    if len(current_runs) < 2:
        return "🧩 PHÂN TÍCH CỤM\n❌ Chưa có cụm đủ dài\n\n", []

    text = "🧩 PHÂN TÍCH CỤM\n\n"
    final_pool: List[Tuple[str, float]] = []

    for d in [2, 3, 4]:
        if len(current_runs) < d:
            continue

        pattern_runs = current_runs[-d:]
        pattern_text = runs_to_text(pattern_runs, limit=d)

        exact_hits = scan_run_hits(BIG_RUNS, pattern_runs, max_len_gap=0)

        history_prev = HISTORY[:-d] if len(HISTORY) > d else []
        history_prev_runs = build_runs(history_prev)
        exact_hits += scan_run_hits(history_prev_runs, pattern_runs, max_len_gap=0)

        soft_hits: List[str] = []
        if len(exact_hits) < 2:
            soft_hits = scan_run_hits(BIG_RUNS, pattern_runs, max_len_gap=1)
            soft_hits += scan_run_hits(history_prev_runs, pattern_runs, max_len_gap=1)

        depth_pool: List[Tuple[str, float]] = []
        for r in exact_hits:
            depth_pool.append((r, 1.0))
        for r in soft_hits:
            depth_pool.append((r, SOFT_WEIGHT))

        if depth_pool:
            c, total_w = weighted_counts(depth_pool)
            text += f"🔸 Cụm {d}: {pattern_text}\n"
            text += f"Khớp: {len(exact_hits)} chính xác, {len(soft_hits)} gần\n"
            text += f"T: {round((c.get('T', 0.0) * 100 / total_w), 1)}% | X: {round((c.get('X', 0.0) * 100 / total_w), 1)}% | Mẫu: {round(total_w, 1)}\n"
            text += f"=> {decision_from_counts(c, total_w)}\n\n"

            if total_w >= MIN_SUPPORT_FOR_CHOT:
                final_pool += depth_pool
        else:
            text += f"🔸 Cụm {d}: {pattern_text}\n"
            text += "Không có khớp cụm, sẽ dùng nền nếu cần\n\n"

    return text, final_pool

# =========================================
# FINAL CHOT
# =========================================

def fallback_baseline() -> Tuple[Counter, float]:
    source = HISTORY[-30:] if len(HISTORY) >= 6 else BIG_DATA[-200:]
    if not source:
        return Counter(), 0.0

    c = Counter(source)
    total = float(sum(c.values()))
    return c, total

def build_final_chot(raw_pool: List[Tuple[str, float]], cluster_pool: List[Tuple[str, float]]) -> str:
    """
    Chốt cuối:
    - ưu tiên cụm
    - vẫn cộng raw vào để soi lại hết
    - nếu không có gì thì dùng nền
    """
    title = "🎯 CHỐT CUỐI THEO CỤM" if cluster_pool else "🎯 CHỐT CUỐI THEO DỮ LIỆU"

    if not raw_pool and not cluster_pool:
        base_counts, base_total = fallback_baseline()
        if base_total <= 0:
            return "🎯 CHỐT CUỐI\nKhông đủ dữ liệu để chốt"

        t = base_counts.get("T", 0)
        x = base_counts.get("X", 0)
        tp = (t * 100 / base_total) if base_total else 0.0
        xp = (x * 100 / base_total) if base_total else 0.0

        if tp >= xp:
            pred = "TÀI"
            pct = tp
        else:
            pred = "XỈU"
            pct = xp

        return f"{title}\nDự đoán: {pred}\nTỷ lệ: {pct:.1f}%"

    # Cụm được ưu tiên hơn raw một chút
    merged: List[Tuple[str, float]] = []
    for r, w in raw_pool:
        merged.append((r, w))
    for r, w in cluster_pool:
        merged.append((r, w * 1.2))

    c, total_w = weighted_counts(merged)
    t = c.get("T", 0.0)
    x = c.get("X", 0.0)

    tp = (t * 100 / total_w) if total_w else 0.0
    xp = (x * 100 / total_w) if total_w else 0.0

    if tp >= xp:
        pred = "TÀI"
        pct = tp
    else:
        pred = "XỈU"
        pct = xp

    return f"{title}\nDự đoán: {pred}\nTỷ lệ: {pct:.1f}%"

def analyze_multi() -> str:
    if len(HISTORY) < 3:
        return "❌ Chưa đủ dữ liệu"

    raw_text, raw_pool = analyze_raw_section()
    cluster_text, cluster_pool = analyze_cluster_section()

    text = "🧠 PHÂN TÍCH\n\n"
    text += raw_text
    text += cluster_text

    final_text = build_final_chot(raw_pool, cluster_pool)
    text += "\n" + final_text

    return text

# =========================================
# TEXT BUILDERS
# =========================================

def dashboard_text() -> str:
    history_preview = " ".join(HISTORY[-20:]) if HISTORY else "(trống)"
    cluster_preview = runs_to_text(build_runs(HISTORY), limit=8)
    return (
        "📌 DASHBOARD\n\n"
        f"📚 BIG_DATA: {len(BIG_DATA)}\n"
        f"🧠 HISTORY: {len(HISTORY)}\n"
        f"🧩 Cụm gần nhất: {cluster_preview}\n"
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
        f"🧩 Cụm gần nhất: {runs_to_text(build_runs(HISTORY), limit=8)}\n"
    )

def guide_text() -> str:
    return (
        "ℹ️ HƯỚNG DẪN\n\n"
        "• Gửi số từ 3 đến 18 để bot lưu vào HISTORY.\n"
        "• 3–10 = X, 11–18 = T.\n"
        "• /reset chỉ xóa HISTORY, không đụng BIG_DATA.\n"
        "• BIG_DATA là dữ liệu gốc từ data.txt hoặc URL.\n"
        "• Bot đọc được cả T/X và số, kể cả có dấu -, dấu phẩy, hoặc xuống dòng.\n"
        "• Mục 🧩 Cụm sẽ xem dữ liệu theo chuỗi chạy liên tiếp.\n"
        "• Mục 🎯 Chốt cuối sẽ gom hết rồi chốt một dòng riêng.\n"
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

    if stripped == "📌 Dashboard":
        await send_menu(update, dashboard_text())
        return

    if stripped == "📊 Thống kê":
        await send_menu(update, stats_text())
        return

    if stripped == "🔄 Train":
        await send_menu(update, analyze_multi())
        return

    if stripped == "🧩 Cụm":
        cluster_text, cluster_pool = analyze_cluster_section()
        reply = cluster_text
        reply += "🎯 KẾT CỤM\n"
        if cluster_pool:
            c, total_w = weighted_counts(cluster_pool)
            reply += build_final_chot([], cluster_pool) + "\n"
            reply += f"Độ lệch: {abs((c.get('T',0.0) - c.get('X',0.0))):.1f}"
        else:
            reply += "Chưa đủ dữ liệu cụm để chốt"
        await send_menu(update, reply)
        return

    if stripped == "🎯 Chốt cuối":
        raw_text, raw_pool = analyze_raw_section()
        cluster_text, cluster_pool = analyze_cluster_section()
        reply = build_final_chot(raw_pool, cluster_pool)
        reply = "🎯 CHỐT CUỐI\n\n" + reply
        await send_menu(update, reply)
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
