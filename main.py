#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

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

MAX_MISMATCHES = int(os.getenv("MAX_MISMATCHES", "1"))
SOFT_WEIGHT = float(os.getenv("SOFT_WEIGHT", "0.6"))
MIN_SUPPORT_FOR_CHOT = int(os.getenv("MIN_SUPPORT_FOR_CHOT", "3"))

TRAIN_DECAY = float(os.getenv("TRAIN_DECAY", "0.9995"))  # càng gần 1 càng giữ dữ liệu cũ nhiều hơn
RAW_MAX_DEPTH = int(os.getenv("RAW_MAX_DEPTH", "6"))
RUN_MAX_DEPTH = int(os.getenv("RUN_MAX_DEPTH", "4"))
LIVE_HISTORY_LOOKBACK = int(os.getenv("LIVE_HISTORY_LOOKBACK", "30"))

# =========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BIG_DATA: List[str] = []
BIG_RUNS: List[Tuple[str, int]] = []
HISTORY: List[str] = []

RAW_MODEL: Dict[str, Dict[str, float]] = {}
RUN_MODEL_EXACT: Dict[str, Dict[str, float]] = {}
RUN_MODEL_SYMBOL: Dict[str, Dict[str, float]] = {}
MODEL_READY = False

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

def run_key_exact(runs: List[Tuple[str, int]]) -> str:
    return "|".join(f"{s}{n}" for s, n in runs)

def run_key_symbol(runs: List[Tuple[str, int]]) -> str:
    return "|".join(s for s, _ in runs)

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
            "train_decay": TRAIN_DECAY,
            "raw_max_depth": RAW_MAX_DEPTH,
            "run_max_depth": RUN_MAX_DEPTH,
            "big_data_size": len(BIG_DATA),
            "big_runs_size": len(BIG_RUNS),
        },
        "raw": RAW_MODEL,
        "run_exact": RUN_MODEL_EXACT,
        "run_symbol": RUN_MODEL_SYMBOL,
    }

    try:
        with open(MODEL_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logging.exception("save_model failed: %s", e)

def load_model() -> bool:
    global RAW_MODEL, RUN_MODEL_EXACT, RUN_MODEL_SYMBOL, MODEL_READY

    if not os.path.exists(MODEL_FILE):
        MODEL_READY = False
        return False

    try:
        with open(MODEL_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)

        RAW_MODEL = payload.get("raw", {}) or {}
        RUN_MODEL_EXACT = payload.get("run_exact", {}) or {}
        RUN_MODEL_SYMBOL = payload.get("run_symbol", {}) or {}

        MODEL_READY = True
        logging.info("Loaded model from %s", MODEL_FILE)
        return True
    except Exception as e:
        logging.exception("load_model failed: %s", e)
        RAW_MODEL = {}
        RUN_MODEL_EXACT = {}
        RUN_MODEL_SYMBOL = {}
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

def train_raw_model(data: List[str], max_depth: int = RAW_MAX_DEPTH, decay: float = TRAIN_DECAY) -> Dict[str, Dict[str, float]]:
    """
    Train model cho chuỗi thô T/X.
    Trọng số giảm dần theo độ cũ để dữ liệu quá xa không đè dữ liệu gần.
    """
    model: Dict[str, Dict[str, float]] = {}
    n = len(data)
    if n < 3:
        return model

    for i in range(n):
        age = (n - 1) - i
        weight = decay ** age

        for d in range(2, max_depth + 1):
            if i + d >= n:
                break

            key = "".join(data[i:i + d])
            nxt = data[i + d]
            if nxt in ("T", "X"):
                _update_model_entry(model, key, nxt, weight)

    return model

def train_run_models(runs: List[Tuple[str, int]], max_depth: int = RUN_MAX_DEPTH, decay: float = TRAIN_DECAY) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    """
    Train model cho cụm:
    - model exact: xét cả symbol và độ dài run
    - model symbol: chỉ xét symbol, giúp nhận diện rộng hơn
    """
    exact_model: Dict[str, Dict[str, float]] = {}
    symbol_model: Dict[str, Dict[str, float]] = {}

    n = len(runs)
    if n < 2:
        return exact_model, symbol_model

    for i in range(n):
        age = (n - 1) - i
        weight = decay ** age

        for d in range(2, max_depth + 1):
            if i + d >= n:
                break

            window = runs[i:i + d]
            nxt = runs[i + d][0]

            if nxt not in ("T", "X"):
                continue

            key_exact = run_key_exact(window)
            key_symbol = run_key_symbol(window)

            _update_model_entry(exact_model, key_exact, nxt, weight)
            _update_model_entry(symbol_model, key_symbol, nxt, weight)

    return exact_model, symbol_model

def train_all() -> None:
    global RAW_MODEL, RUN_MODEL_EXACT, RUN_MODEL_SYMBOL, MODEL_READY

    RAW_MODEL = train_raw_model(BIG_DATA)
    RUN_MODEL_EXACT, RUN_MODEL_SYMBOL = train_run_models(BIG_RUNS)
    MODEL_READY = True

    save_model()
    logging.info("Train done. RAW=%d, RUN_EXACT=%d, RUN_SYMBOL=%d",
                 len(RAW_MODEL), len(RUN_MODEL_EXACT), len(RUN_MODEL_SYMBOL))

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
    Chuyển một entry model thành trọng số vote.
    Support càng lớn, lệch càng mạnh thì vote càng cao.
    """
    t = float(entry.get("T", 0.0))
    x = float(entry.get("X", 0.0))
    support = float(entry.get("support", 0.0))
    total = t + x

    if support <= 0 or total <= 0:
        return []

    certainty = abs(t - x) / total
    weight = priority * (1.0 + math.log1p(total)) * certainty

    if weight <= 0:
        return []

    return [
        ("T", weight * (t / total)),
        ("X", weight * (x / total)),
    ]

def lookup_best_model(model: Dict[str, Dict[str, float]], keys: List[str]) -> Optional[Dict[str, float]]:
    """
    Trả về entry đầu tiên khớp theo thứ tự ưu tiên keys.
    """
    for key in keys:
        entry = model.get(key)
        if entry and float(entry.get("support", 0.0)) > 0:
            return entry
    return None

# =========================================
# ANALYSIS - RAW
# =========================================

def analyze_raw_section() -> Tuple[str, List[Tuple[str, float]]]:
    if len(HISTORY) < 3:
        return "🔹 CẦU THƯỜNG\n❌ Chưa đủ dữ liệu\n\n", []

    text = "🔹 CẦU THƯỜNG\n\n"
    final_pool: List[Tuple[str, float]] = []

    history_live = HISTORY[-LIVE_HISTORY_LOOKBACK:] if len(HISTORY) > LIVE_HISTORY_LOOKBACK else HISTORY[:]

    depths = [6, 5, 4, 3]
    for d in depths:
        if len(history_live) < d + 1:
            continue

        pattern = history_live[-d:]
        pattern_text = "".join(pattern)

        entry = lookup_best_model(
            RAW_MODEL,
            ["".join(pattern)]
        )

        if entry:
            votes = entry_vote(entry, priority=1.0)
            c, total_w = weighted_counts(votes)

            text += f"🔸 Pattern {d}: {pattern_text}\n"
            text += f"Support: {round(float(entry.get('support', 0.0)), 2)}\n"
            text += f"T: {round((float(entry.get('T', 0.0)) * 100 / float(entry.get('support', 1.0))), 1)}% | "
            text += f"X: {round((float(entry.get('X', 0.0)) * 100 / float(entry.get('support', 1.0))), 1)}%\n"
            text += f"=> {decision_from_counts(c, total_w)}\n\n"

            if float(entry.get("support", 0.0)) >= MIN_SUPPORT_FOR_CHOT:
                final_pool += votes
        else:
            text += f"🔸 Pattern {d}: {pattern_text}\n"
            text += "Không có khớp model\n\n"

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

    for d in [4, 3, 2]:
        if len(current_runs) < d + 1:
            continue

        pattern_runs = current_runs[-d:]
        pattern_text = runs_to_text(pattern_runs, limit=d)

        exact_key = run_key_exact(pattern_runs)
        symbol_key = run_key_symbol(pattern_runs)

        exact_entry = lookup_best_model(RUN_MODEL_EXACT, [exact_key])
        symbol_entry = lookup_best_model(RUN_MODEL_SYMBOL, [symbol_key])

        votes: List[Tuple[str, float]] = []

        if exact_entry:
            votes += entry_vote(exact_entry, priority=1.25)

        if symbol_entry:
            votes += entry_vote(symbol_entry, priority=0.9)

        if votes:
            c, total_w = weighted_counts(votes)

            total_support = 0.0
            if exact_entry:
                total_support += float(exact_entry.get("support", 0.0))
            if symbol_entry:
                total_support += float(symbol_entry.get("support", 0.0))

            text += f"🔸 Cụm {d}: {pattern_text}\n"
            text += f"Support: {round(total_support, 2)}\n"
            if exact_entry:
                text += (
                    f"Exact T: {round(float(exact_entry.get('T', 0.0)) * 100 / max(float(exact_entry.get('support', 1.0)), 1.0), 1)}% | "
                    f"X: {round(float(exact_entry.get('X', 0.0)) * 100 / max(float(exact_entry.get('support', 1.0)), 1.0), 1)}%\n"
                )
            if symbol_entry:
                text += (
                    f"Symbol T: {round(float(symbol_entry.get('T', 0.0)) * 100 / max(float(symbol_entry.get('support', 1.0)), 1.0), 1)}% | "
                    f"X: {round(float(symbol_entry.get('X', 0.0)) * 100 / max(float(symbol_entry.get('support', 1.0)), 1.0), 1)}%\n"
                )

            text += f"=> {decision_from_counts(c, total_w)}\n\n"

            if total_support >= MIN_SUPPORT_FOR_CHOT:
                final_pool += votes
        else:
            text += f"🔸 Cụm {d}: {pattern_text}\n"
            text += "Không có khớp model\n\n"

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
    - raw vẫn cộng vào
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

    merged: List[Tuple[str, float]] = []
    for r, w in raw_pool:
        merged.append((r, w))
    for r, w in cluster_pool:
        merged.append((r, w * 1.2))  # ưu tiên cụm hơn raw một chút

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

def model_status_text() -> str:
    return (
        "🧠 MODEL STATUS\n\n"
        f"READY: {MODEL_READY}\n"
        f"RAW keys: {len(RAW_MODEL)}\n"
        f"RUN exact keys: {len(RUN_MODEL_EXACT)}\n"
        f"RUN symbol keys: {len(RUN_MODEL_SYMBOL)}\n"
        f"TRAIN_DECAY: {TRAIN_DECAY}\n"
        f"RAW_MAX_DEPTH: {RAW_MAX_DEPTH}\n"
        f"RUN_MAX_DEPTH: {RUN_MAX_DEPTH}\n"
    )

def dashboard_text() -> str:
    history_preview = " ".join(HISTORY[-20:]) if HISTORY else "(trống)"
    cluster_preview = runs_to_text(build_runs(HISTORY), limit=8)
    return (
        "📌 DASHBOARD\n\n"
        f"📚 BIG_DATA: {len(BIG_DATA)}\n"
        f"🧠 HISTORY: {len(HISTORY)}\n"
        f"🧩 Cụm gần nhất: {cluster_preview}\n"
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
        f"RUN exact keys: {len(RUN_MODEL_EXACT)}\n"
        f"RUN symbol keys: {len(RUN_MODEL_SYMBOL)}"
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

    if stripped == "🧩 Cụm":
        cluster_text, cluster_pool = analyze_cluster_section()
        reply = cluster_text
        reply += "🎯 KẾT CỤM\n"
        if cluster_pool:
            c, total_w = weighted_counts(cluster_pool)
            reply += build_final_chot([], cluster_pool) + "\n"
            reply += f"Độ lệch: {abs((c.get('T', 0.0) - c.get('X', 0.0))):.1f}"
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

    # Nếu có model cũ thì tải trước, không có thì train mới
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
