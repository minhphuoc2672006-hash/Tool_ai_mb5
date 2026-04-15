#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

import requests
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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
MODEL_FILE = os.getenv("MODEL_FILE", "model.json").strip()

PATTERN_LEN = int(os.getenv("PATTERN_LEN", "25"))
TRAIN_DECAY = float(os.getenv("TRAIN_DECAY", "0.9995"))
LIVE_HISTORY_LOOKBACK = int(os.getenv("LIVE_HISTORY_LOOKBACK", "30"))
MIN_SUPPORT_FOR_CHOT = float(os.getenv("MIN_SUPPORT_FOR_CHOT", "3"))

# =========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BIG_DATA: List[str] = []
HISTORY: List[str] = []

RAW_MODEL: Dict[str, Dict[str, float]] = {}
MODEL_READY = False

# =========================================
# UI
# =========================================

def menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📌 Dashboard"), KeyboardButton("➕ Nhập dữ liệu")],
        [KeyboardButton("📊 Thống kê"), KeyboardButton("🔄 Train")],
        [KeyboardButton("🎯 Chốt cuối"), KeyboardButton("🧹 Reset")],
        [KeyboardButton("🔁 Reload data"), KeyboardButton("ℹ️ Hướng dẫn")],
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
# MODEL KEY
# =========================================

def pattern_key(seq: List[str]) -> str:
    return "".join(seq)

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

def save_state() -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"h": HISTORY}, f, ensure_ascii=False)
    except Exception as e:
        logging.exception("save_state failed: %s", e)

def load_state() -> None:
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
        logging.exception("load_state failed: %s", e)
        HISTORY = []

def save_model() -> None:
    payload = {
        "meta": {
            "pattern_len": PATTERN_LEN,
            "train_decay": TRAIN_DECAY,
            "big_data_size": len(BIG_DATA),
        },
        "raw": RAW_MODEL,
    }

    try:
        with open(MODEL_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logging.exception("save_model failed: %s", e)

def load_model() -> bool:
    global RAW_MODEL, MODEL_READY

    if not os.path.exists(MODEL_FILE):
        MODEL_READY = False
        return False

    try:
        with open(MODEL_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)

        RAW_MODEL = payload.get("raw", {}) or {}
        MODEL_READY = True

        logging.info("Loaded model from %s", MODEL_FILE)
        return True
    except Exception as e:
        logging.exception("load_model failed: %s", e)
        RAW_MODEL = {}
        MODEL_READY = False
        return False

# =========================================
# TRAINING
# =========================================

def _update_model_entry(model: Dict[str, Dict[str, float]], key: str, nxt: str, weight: float) -> None:
    if key not in model:
        model[key] = {"T": 0.0, "X": 0.0, "support": 0.0}

    model[key][nxt] += weight
    model[key]["support"] += weight

def train_raw_model(data: List[str], pattern_len: int = PATTERN_LEN, decay: float = TRAIN_DECAY) -> Dict[str, Dict[str, float]]:
    """
    Train đúng một pattern duy nhất:
    - lấy chuỗi dài PATTERN_LEN
    - dự đoán kết quả ngay sau chuỗi đó
    - dữ liệu càng cũ thì weight càng giảm
    """
    model: Dict[str, Dict[str, float]] = {}
    n = len(data)

    if n < pattern_len + 1:
        return model

    for i in range(n - pattern_len):
        age = (n - 1) - i
        weight = decay ** age

        key = "".join(data[i:i + pattern_len])
        nxt = data[i + pattern_len]

        if nxt in ("T", "X"):
            _update_model_entry(model, key, nxt, weight)

    return model

def train_all() -> None:
    global RAW_MODEL, MODEL_READY

    RAW_MODEL = train_raw_model(BIG_DATA)
    MODEL_READY = True
    save_model()

    logging.info("Train done. RAW keys=%d", len(RAW_MODEL))

# =========================================
# SCORING / DECISION
# =========================================

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

def entry_vote(entry: Dict[str, float], priority: float = 1.0) -> List[Tuple[str, float]]:
    """
    Chuyển model entry thành vote.
    Có chặn trường hợp quá lệch 100% để giảm dính cầu giả.
    """
    t = float(entry.get("T", 0.0))
    x = float(entry.get("X", 0.0))
    support = float(entry.get("support", 0.0))
    total = t + x

    if support <= 0 or total <= 0:
        return []

    # Nếu quá lệch tuyệt đối thì giảm độ tin cậy để tránh overfit
    if t == 0 or x == 0:
        certainty = 0.4
    else:
        certainty = abs(t - x) / total

    entropy = 0.0
    pt = t / total
    px = x / total
    if pt > 0:
        entropy -= pt * math.log2(pt)
    if px > 0:
        entropy -= px * math.log2(px)

    # entropy thấp quá thì coi như mẫu quá cứng, dễ dính cầu fake
    if entropy < 0.3:
        return []

    weight = priority * (1.0 + math.log1p(total)) * certainty
    if weight <= 0:
        return []

    return [
        ("T", weight * (t / total)),
        ("X", weight * (x / total)),
    ]

def fallback_baseline() -> Tuple[Counter, float]:
    source = HISTORY[-30:] if len(HISTORY) >= 6 else BIG_DATA[-200:]
    if not source:
        return Counter(), 0.0

    c = Counter(source)
    total = float(sum(c.values()))
    return c, total

# =========================================
# ANALYSIS - ONE PATTERN ONLY
# =========================================

def analyze_pattern25() -> Tuple[str, List[Tuple[str, float]]]:
    if len(HISTORY) < PATTERN_LEN:
        return f"🔹 CẦU THƯỜNG\n❌ Chưa đủ dữ liệu cho pattern {PATTERN_LEN}\n\n", []

    text = "🔹 CẦU THƯỜNG\n\n"
    final_pool: List[Tuple[str, float]] = []

    history_live = HISTORY[-LIVE_HISTORY_LOOKBACK:] if len(HISTORY) > LIVE_HISTORY_LOOKBACK else HISTORY[:]
    if len(history_live) < PATTERN_LEN:
        pattern_source = HISTORY
    else:
        pattern_source = history_live

    pattern = pattern_source[-PATTERN_LEN:]
    key = pattern_key(pattern)

    entry = RAW_MODEL.get(key)

    if entry:
        votes = entry_vote(entry, priority=1.0)
        c, total_w = weighted_counts(votes)

        support = float(entry.get("support", 0.0))
        t_pct = round(float(entry.get("T", 0.0)) * 100 / max(support, 1.0), 1)
        x_pct = round(float(entry.get("X", 0.0)) * 100 / max(support, 1.0), 1)

        text += f"🔸 Pattern {PATTERN_LEN}: {key}\n"
        text += f"Support: {round(support, 2)}\n"
        text += f"T: {t_pct}% | X: {x_pct}%\n"
        text += f"=> {decision_from_counts(c, total_w)}\n\n"

        if support >= MIN_SUPPORT_FOR_CHOT:
            final_pool += votes
    else:
        text += f"🔸 Pattern {PATTERN_LEN}: {key}\n"
        text += "Không có khớp model\n\n"

    return text, final_pool

def build_final_chot(raw_pool: List[Tuple[str, float]]) -> str:
    title = "🎯 CHỐT CUỐI THEO PATTERN 25"

    if not raw_pool:
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

    c, total_w = weighted_counts(raw_pool)
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
    if len(HISTORY) < PATTERN_LEN:
        return f"❌ Chưa đủ dữ liệu để phân tích pattern {PATTERN_LEN}"

    raw_text, raw_pool = analyze_pattern25()
    final_text = build_final_chot(raw_pool)

    text = "🧠 PHÂN TÍCH\n\n"
    text += raw_text
    text += "\n" + final_text
    return text

# =========================================
# TEXT BUILDERS
# =========================================

def model_status_text() -> str:
    return (
        "🧠 MODEL STATUS\n\n"
        f"READY: {MODEL_READY}\n"
        f"RAW keys: {len(RAW_MODEL)}\n"
        f"PATTERN_LEN: {PATTERN_LEN}\n"
        f"TRAIN_DECAY: {TRAIN_DECAY}\n"
    )

def dashboard_text() -> str:
    history_preview = " ".join(HISTORY[-20:]) if HISTORY else "(trống)"
    return (
        "📌 DASHBOARD\n\n"
        f"📚 BIG_DATA: {len(BIG_DATA)}\n"
        f"🧠 HISTORY: {len(HISTORY)}\n"
        f"🔎 20 kết quả gần nhất: {history_preview}\n\n"
        f"{model_status_text()}\n"
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
        f"• Bot chỉ dùng đúng 1 pattern duy nhất dài {PATTERN_LEN}.\n"
        "• /train sẽ train lại model từ BIG_DATA và lưu ra file.\n"
        "• /reloaddata sẽ tải lại dữ liệu gốc rồi train luôn.\n"
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
    save_state()
    await send_menu(update, "✅ Reset xong phần lịch sử nhập tay. BIG_DATA vẫn giữ nguyên.")

async def train_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not BIG_DATA:
        await send_menu(update, "❌ Chưa có BIG_DATA để train.")
        return

    train_all()
    await send_menu(
        update,
        "✅ Train xong.\n"
        f"RAW keys: {len(RAW_MODEL)}\n"
        f"Pattern: {PATTERN_LEN}"
    )

async def reload_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    load_data()
    if BIG_DATA:
        train_all()
        await send_menu(update, f"🔄 Đã tải lại BIG_DATA: {len(BIG_DATA)} và train lại model xong.")
    else:
        await send_menu(update, "❌ Không tải được BIG_DATA.")

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
        await train_cmd(update, ctx)
        return

    if stripped == "🎯 Chốt cuối":
        _, raw_pool = analyze_pattern25()
        reply = "🎯 CHỐT CUỐI\n\n" + build_final_chot(raw_pool)
        await send_menu(update, reply)
        return

    if stripped == "🧹 Reset":
        HISTORY.clear()
        save_state()
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

    added: List[str] = []
    ignored: List[str] = []

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

    save_state()

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

    load_state()
    load_data()

    # Tải model trước, không có thì train mới
    if not load_model():
        if BIG_DATA:
            train_all()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("train", train_cmd))
    app.add_handler(CommandHandler("reloaddata", reload_data))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
