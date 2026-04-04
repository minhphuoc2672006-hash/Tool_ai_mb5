import os
import re
import json
import math
import sqlite3
import asyncio
import logging
import time
from io import BytesIO
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from telegram import Update
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "ai_state.db")

THRESHOLD = int(os.getenv("THRESHOLD", "11"))
LOW_LABEL = os.getenv("LOW_LABEL", "Xỉu")
HIGH_LABEL = os.getenv("HIGH_LABEL", "Tài")

RECENT_CACHE = int(os.getenv("RECENT_CACHE", "500"))
MAX_KEEP_HISTORY = int(os.getenv("MAX_KEEP_HISTORY", "0"))
MAX_INPUT_NUMS = int(os.getenv("MAX_INPUT_NUMS", "120"))
USER_CACHE_LIMIT = int(os.getenv("USER_CACHE_LIMIT", "500"))
MIN_ANALYSIS_LEN = int(os.getenv("MIN_ANALYSIS_LEN", "6"))
HISTORY_ANALYSIS_LIMIT = int(os.getenv("HISTORY_ANALYSIS_LIMIT", "0"))

MIN_PREDICTION_DATA = int(os.getenv("MIN_PREDICTION_DATA", "20"))
CLEAR_PATTERN_MIN_SCORE = int(os.getenv("CLEAR_PATTERN_MIN_SCORE", "80"))
LOSS_STREAK_LIMIT = int(os.getenv("LOSS_STREAK_LIMIT", "5"))

# Chờ thêm 1 nhịp để xác nhận cầu mới
CONFIRM_NEW_PATTERN_MIN_SCORE = int(os.getenv("CONFIRM_NEW_PATTERN_MIN_SCORE", "88"))
# Alias để không lỗi nếu còn chỗ nào gọi tên cũ
CONFIRM_PATTERN_MIN_SCORE = CONFIRM_NEW_PATTERN_MIN_SCORE

# Robot hiển thị chờ phân tích
ROBOT_ANALYZE_DELAY = float(os.getenv("ROBOT_ANALYZE_DELAY", "5"))
ROBOT_IMAGE_PATH = os.getenv("ROBOT_IMAGE_PATH", "robot.jpg")

if not TOKEN:
    raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN")

DB_LOCK = asyncio.Lock()
STATE_LOCK = asyncio.Lock()
users: Dict[int, Dict[str, Any]] = {}


def ensure_robot_asset() -> str:
    if os.path.exists(ROBOT_IMAGE_PATH):
        return ROBOT_IMAGE_PATH
    try:
        fig, ax = plt.subplots(figsize=(5, 3), dpi=150)
        fig.patch.set_facecolor("#0f1117")
        ax.set_facecolor("#11151c")
        ax.axis("off")
        ax.text(0.5, 0.60, "ROBOT", ha="center", va="center", fontsize=28, fontweight="bold", color="white")
        ax.text(0.5, 0.35, "ĐANG PHÂN TÍCH...", ha="center", va="center", fontsize=14, color="white")
        fig.savefig(ROBOT_IMAGE_PATH, format="jpg", bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
    except Exception as e:
        logger.exception("Không tạo được file robot: %s", e)
    return ROBOT_IMAGE_PATH


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    return conn


async def run_db_work(fn):
    return await asyncio.to_thread(fn)


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL DEFAULT (unixepoch())
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                raw_value INTEGER NOT NULL,
                label TEXT NOT NULL,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );

            CREATE INDEX IF NOT EXISTS idx_history_chat_id_id ON history(chat_id, id);
            """
        )
        conn.commit()


def prune_history(conn: sqlite3.Connection, chat_id: int, keep_limit: int) -> None:
    if keep_limit <= 0:
        return
    row = conn.execute(
        "SELECT id FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
        (chat_id, max(0, keep_limit - 1)),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM history WHERE chat_id = ? AND id < ?", (chat_id, int(row["id"])))


async def append_history(chat_id: int, items: List[Tuple[int, str]]) -> None:
    if not items:
        return

    def _work():
        with db_connect() as conn:
            for raw_value, label in items:
                conn.execute(
                    "INSERT INTO history (chat_id, raw_value, label) VALUES (?, ?, ?)",
                    (chat_id, int(raw_value), label),
                )
            prune_history(conn, chat_id, MAX_KEEP_HISTORY)
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)


async def load_history_rows(chat_id: int, limit: int = HISTORY_ANALYSIS_LIMIT) -> List[Tuple[int, str]]:
    def _work():
        with db_connect() as conn:
            if limit and limit > 0:
                rows = conn.execute(
                    "SELECT raw_value, label FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                    (chat_id, limit),
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = conn.execute(
                    "SELECT raw_value, label FROM history WHERE chat_id = ? ORDER BY id ASC",
                    (chat_id,),
                ).fetchall()
            return [(int(r["raw_value"]), str(r["label"])) for r in rows]

    async with DB_LOCK:
        return await run_db_work(_work)


def new_state() -> Dict[str, Any]:
    return {
        "values": [],
        "labels": [],
        "total": 0,
        "low_count": 0,
        "high_count": 0,
        "last_prediction_label": None,
        "last_prediction_conf": 0,
        "last_prediction_result": "CHƯA RÕ",
        "prediction_total": 0,
        "prediction_hits": 0,
        "prediction_misses": 0,
        "current_correct_streak": 0,
        "current_wrong_streak": 0,
        "max_correct_streak": 0,
        "max_wrong_streak": 0,
        "model_accuracy": {"pattern": 50, "structure": 50},
        "last_note": "",
        "last_structure": "CHƯA ĐỦ DỮ LIỆU",
        "last_mode": "NORMAL",
        "last_model_predictions": {},
        "last_gate_status": "CHỜ",
        "last_gate_reason": "Chưa kiểm tra",
        "last_detected_pattern": "",
        "last_detected_hint": None,
        "last_chart_label": "",
        "last_chart_conf": 0,
        "cooldown_active": False,
        "cooldown_reason": "",
        "last_relearn_note": "",
        "last_resume_note": "",
        "last_relearn_snapshot": "",
        "last_relearn_total": 0,
        "pattern_confirm_sig": "",
        "pattern_confirm_count": 0,
    }


def _safe_tail(seq: List[Any], limit: int) -> List[Any]:
    return list(seq[-limit:]) if limit > 0 and len(seq) > limit else list(seq)


def trim_state_memory(d: Dict[str, Any]) -> None:
    d["values"] = _safe_tail(d.get("values", []), RECENT_CACHE)
    d["labels"] = _safe_tail(d.get("labels", []), RECENT_CACHE)


def rebuild_counters_from_labels(d: Dict[str, Any], labels: List[str]) -> None:
    d["low_count"] = labels.count(LOW_LABEL)
    d["high_count"] = labels.count(HIGH_LABEL)
    d["total"] = len(labels)


def repair_state(d: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(d, dict):
        d = new_state()

    for k in ("values", "labels"):
        if not isinstance(d.get(k), list):
            d[k] = []

    if not isinstance(d.get("model_accuracy"), dict):
        d["model_accuracy"] = {"pattern": 50, "structure": 50}

    defaults = new_state()
    for k, v in defaults.items():
        d.setdefault(k, v)

    n = min(len(d["values"]), len(d["labels"]))
    d["values"] = d["values"][-n:] if n else []
    d["labels"] = d["labels"][-n:] if n else []

    trim_state_memory(d)
    rebuild_counters_from_labels(d, d.get("labels", []))
    return d


def trim_cache() -> None:
    if len(users) <= USER_CACHE_LIMIT:
        return
    overflow = len(users) - USER_CACHE_LIMIT
    for chat_id in list(users.keys())[:overflow]:
        users.pop(chat_id, None)


def map_value(n: int) -> str:
    return HIGH_LABEL if n >= THRESHOLD else LOW_LABEL


def opposite_label(label: str) -> str:
    return HIGH_LABEL if label == LOW_LABEL else LOW_LABEL


def get_key(update: Update) -> int:
    return update.effective_chat.id


def parse_input(text: str) -> List[int]:
    nums: List[int] = []
    text = (text or "").strip()
    for x in re.findall(r"\d+", text):
        try:
            n = int(x)
            if n >= 0:
                nums.append(n)
        except Exception:
            continue
    return nums[:MAX_INPUT_NUMS]


async def load_state(chat_id: int, force_reload: bool = False) -> Dict[str, Any]:
    if not force_reload and chat_id in users:
        return repair_state(users[chat_id])

    def _work():
        with db_connect() as conn:
            return conn.execute(
                "SELECT state_json FROM chat_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()

    async with DB_LOCK:
        row = await run_db_work(_work)

    state = new_state()
    if row:
        try:
            state.update(json.loads(row["state_json"]))
        except Exception:
            pass

    state = repair_state(state)
    users[chat_id] = state
    trim_cache()
    return state


async def save_state(chat_id: int, state: Dict[str, Any]) -> None:
    state = repair_state(state)

    def _work():
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_state (chat_id, state_json, updated_at)
                VALUES (?, ?, unixepoch())
                ON CONFLICT(chat_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (chat_id, json.dumps(state, ensure_ascii=False)),
            )
            prune_history(conn, chat_id, MAX_KEEP_HISTORY)
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def current_streak(labels: List[str]) -> Tuple[Optional[str], int]:
    if not labels:
        return None, 0
    last = labels[-1]
    streak = 1
    for i in range(len(labels) - 2, -1, -1):
        if labels[i] == last:
            streak += 1
        else:
            break
    return last, streak


def run_length_encode(labels: List[str]) -> List[Tuple[str, int]]:
    if not labels:
        return []
    out: List[Tuple[str, int]] = []
    cur = labels[0]
    count = 1
    for x in labels[1:]:
        if x == cur:
            count += 1
        else:
            out.append((cur, count))
            cur = x
            count = 1
    out.append((cur, count))
    return out


def recent_ratio(labels: List[str], window: int) -> Dict[str, float]:
    tail = labels[-window:] if len(labels) > window else labels[:]
    if not tail:
        return {LOW_LABEL: 0.5, HIGH_LABEL: 0.5}
    c = Counter(tail)
    total = c[LOW_LABEL] + c[HIGH_LABEL]
    if total <= 0:
        return {LOW_LABEL: 0.5, HIGH_LABEL: 0.5}
    return {LOW_LABEL: c[LOW_LABEL] / total, HIGH_LABEL: c[HIGH_LABEL] / total}


def alternating_tail(labels: List[str], window: int = 6) -> Tuple[bool, float]:
    tail = labels[-window:] if len(labels) >= window else labels[:]
    if len(tail) < 4:
        return False, 0.0
    changes = sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])
    ratio = changes / (len(tail) - 1)
    return all(tail[i] != tail[i - 1] for i in range(1, len(tail))), ratio


def entropy_score(labels: List[str], window: int = 20) -> float:
    tail = labels[-window:] if len(labels) > window else labels[:]
    if len(tail) < 4:
        return 0.0
    c = Counter(tail)
    total = len(tail)
    ent = 0.0
    for v in c.values():
        p = v / total
        ent -= p * math.log2(p)
    return ent


def volatility_score(labels: List[str], window: int = 12) -> float:
    tail = labels[-window:] if len(labels) > window else labels[:]
    if len(tail) < 4:
        return 0.0
    changes = sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])
    return changes / (len(tail) - 1)


def detect_repeat_block(labels: List[str], max_block: int = 3) -> Optional[Dict[str, Any]]:
    tail = labels[-12:] if len(labels) > 12 else labels[:]
    for block in range(1, max_block + 1):
        if len(tail) >= block * 2:
            a = tail[-(block * 2):-block]
            b = tail[-block:]
            if a == b:
                return {"name": f"LẶP KHỐI {block}", "detail": f"Khối {block} mẫu gần nhất đang lặp", "score": min(78 + block * 4, 92), "hint": a[0] if a else None}
    return None


def detect_motif_repeat(labels: List[str], max_motif: int = 8) -> Optional[Dict[str, Any]]:
    tail = labels[-40:] if len(labels) > 40 else labels[:]
    if len(tail) < 4:
        return None

    best: Optional[Dict[str, Any]] = None
    for m in range(1, min(max_motif, len(tail) // 2) + 1):
        motif = tail[-m:]
        reps = 1
        idx = len(tail) - m
        while idx - m >= 0 and tail[idx - m:idx] == motif:
            reps += 1
            idx -= m

        if reps >= 2:
            if m == 1:
                name = "BỆT"
                hint = motif[0]
                score = min(70 + reps * 6, 95)
            elif m == 2 and motif[0] != motif[1]:
                name = "XEN KẼ"
                hint = opposite_label(tail[-1])
                score = min(76 + reps * 4, 94)
            else:
                name = f"LẶP MẪU {m}"
                hint = motif[0]
                score = min(72 + reps * 5, 94)

            cand = {"name": name, "detail": f"Mẫu {m} lặp {reps} lần", "score": score, "hint": hint}
            if best is None or cand["score"] > best["score"]:
                best = cand
    return best


def detect_explicit_pair_patterns(labels: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if len(labels) < 4:
        return out
    a, b, c, d = labels[-4], labels[-3], labels[-2], labels[-1]
    if a != b and a == c and b == d:
        out.append({"name": "1-1", "detail": "Mẫu luân phiên 1-1", "score": 90, "hint": a})
    if a == b and c == d and a != c:
        out.append({"name": "2-2", "detail": "Mẫu chia cặp 2-2", "score": 86, "hint": a})
    if len(labels) >= 6:
        t = labels[-6:]
        if t[0] == t[2] == t[4] and t[1] == t[3] == t[5] and t[0] != t[1]:
            out.append({"name": "XEN KẼ SÂU", "detail": "Luân phiên đều trong 6 mẫu gần nhất", "score": 94, "hint": t[0]})
    return out


def detect_run_cycle(labels: List[str]) -> Optional[Dict[str, Any]]:
    runs = run_length_encode(labels)
    if len(runs) < 4:
        return None
    a1, l1 = runs[-4]
    b1, m1 = runs[-3]
    a2, l2 = runs[-2]
    b2, m2 = runs[-1]
    if a1 == a2 and b1 == b2 and l1 == l2 and m1 == m2 and a1 != b1:
        return {"name": f"CẦU {l1}-{m1}", "detail": f"Chu kỳ 2 khối lặp: {l1}-{m1}", "score": min(82 + (l1 + m1) * 2, 95), "hint": a2}
    return None


def detect_bias(labels: List[str]) -> Optional[Dict[str, Any]]:
    if len(labels) < 12:
        return None
    r6 = recent_ratio(labels, 6)
    r12 = recent_ratio(labels, 12)
    r24 = recent_ratio(labels, 24)
    gap6 = abs(r6[LOW_LABEL] - r6[HIGH_LABEL])
    gap12 = abs(r12[LOW_LABEL] - r12[HIGH_LABEL])
    gap24 = abs(r24[LOW_LABEL] - r24[HIGH_LABEL])

    if gap6 >= 0.50:
        winner = LOW_LABEL if r6[LOW_LABEL] > r6[HIGH_LABEL] else HIGH_LABEL
        return {"name": "NGHIÊNG NHẸ", "detail": f"Đuôi 6 nghiêng về {winner}", "score": 72, "hint": winner}
    if gap12 >= 0.35:
        winner = LOW_LABEL if r12[LOW_LABEL] > r12[HIGH_LABEL] else HIGH_LABEL
        return {"name": "NGHIÊNG", "detail": f"Đuôi 12 nghiêng về {winner}", "score": 78, "hint": winner}
    if gap24 >= 0.25:
        winner = LOW_LABEL if r24[LOW_LABEL] > r24[HIGH_LABEL] else HIGH_LABEL
        return {"name": "XU HƯỚNG", "detail": f"24 mẫu gần đây nghiêng về {winner}", "score": 80, "hint": winner}
    if gap24 < 0.10:
        return {"name": "CÂN BẰNG", "detail": "Hai phía gần như ngang nhau", "score": 65, "hint": None}
    return None


def detect_reversal(labels: List[str]) -> Optional[Dict[str, Any]]:
    if len(labels) < 12:
        return None
    first = labels[-12:-6]
    second = labels[-6:]
    if not first or not second:
        return None
    c1 = Counter(first)
    c2 = Counter(second)
    d1 = c1[HIGH_LABEL] - c1[LOW_LABEL]
    d2 = c2[HIGH_LABEL] - c2[LOW_LABEL]
    if d1 == 0 or d2 == 0:
        return None
    if (d1 > 0 > d2) or (d1 < 0 < d2):
        return {"name": "ĐẢO CHIỀU", "detail": "Hai cụm gần nhất đang đổi hướng", "score": 84, "hint": HIGH_LABEL if d2 > 0 else LOW_LABEL}
    return None


def detect_all_patterns(labels: List[str]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    for item in (
        detect_motif_repeat(labels, 8),
        *detect_explicit_pair_patterns(labels),
        detect_run_cycle(labels),
        detect_repeat_block(labels, 3),
        detect_reversal(labels),
        detect_bias(labels),
    ):
        if item:
            patterns.append(item)

    last, streak = current_streak(labels)
    if last in (LOW_LABEL, HIGH_LABEL) and streak >= 3:
        patterns.append({"name": "BỆT", "detail": f"{last} x{streak}", "score": min(68 + streak * 6, 95), "hint": last})

    alt, alt_ratio = alternating_tail(labels, 6)
    if alt and alt_ratio >= 0.80 and len(labels) >= 6:
        patterns.append({"name": "XEN KẼ", "detail": "Chuỗi đổi liên tục", "score": 88, "hint": opposite_label(labels[-1])})

    return sorted(patterns, key=lambda x: x.get("score", 0), reverse=True)[:12]


def build_report(labels: List[str]) -> Dict[str, Any]:
    c = Counter(labels)
    last, streak = current_streak(labels)
    alt, alt_ratio = alternating_tail(labels, 6)
    r6 = recent_ratio(labels, 6)
    r12 = recent_ratio(labels, 12)
    r24 = recent_ratio(labels, 24)
    ent = entropy_score(labels, 20)
    vol = volatility_score(labels, 12)
    patterns = detect_all_patterns(labels)

    if len(labels) < 4:
        structure = "CHƯA ĐỦ DỮ LIỆU"
        detail = "Cần thêm kết quả"
    elif patterns:
        structure = patterns[0]["name"]
        detail = patterns[0]["detail"]
    else:
        if alt and alt_ratio >= 0.80:
            structure = "XEN KẼ"
            detail = "Chuỗi đổi liên tục"
        elif streak >= 4 and last in (LOW_LABEL, HIGH_LABEL):
            structure = "BỆT"
            detail = f"{last} x{streak}"
        elif vol >= 0.65:
            structure = "CHUYỂN PHA"
            detail = "Nhịp đang đổi nhanh"
        elif ent <= 0.85:
            structure = "ỔN ĐỊNH"
            detail = "Mẫu gần đây khá đều"
        else:
            structure = "TRUNG TÍNH"
            detail = "Chưa có tín hiệu quá rõ"

    return {
        "total": len(labels),
        "low": c.get(LOW_LABEL, 0),
        "high": c.get(HIGH_LABEL, 0),
        "labels": labels,
        "last_label": last,
        "streak": streak,
        "alternating": alt,
        "alt_ratio": alt_ratio,
        "structure": structure,
        "detail": detail,
        "recent_6": r6,
        "recent_12": r12,
        "recent_24": r24,
        "entropy": ent,
        "volatility": vol,
        "patterns": patterns,
    }


def advanced_metrics(labels: List[str]) -> Dict[str, Any]:
    if not labels:
        return {"max_streak": 0, "r10_high": 0.5, "r20_high": 0.5, "momentum": 0.0, "noise": 0.0, "reversal": 0.0}
    max_streak = 1
    cur = 1
    for i in range(1, len(labels)):
        if labels[i] == labels[i - 1]:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 1
    last10 = labels[-10:]
    last20 = labels[-20:]
    r10 = safe_div(last10.count(HIGH_LABEL), len(last10)) if last10 else 0.5
    r20 = safe_div(last20.count(HIGH_LABEL), len(last20)) if last20 else 0.5
    momentum = r10 - r20
    changes = sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])
    noise = safe_div(changes, len(labels))
    reversal = abs(momentum) * 100
    return {"max_streak": max_streak, "r10_high": r10, "r20_high": r20, "momentum": momentum, "noise": noise, "reversal": reversal}


def extract_chart_features(labels: List[str]) -> Dict[str, Any]:
    if not labels:
        return {"trend": 0.0, "trend_label": "TRUNG TÍNH", "reversal_rate": 0.0, "smoothness": 0.0, "max_streak": 0, "last_value": None, "last_5_high": 0.5, "prev_5_high": 0.5}

    ys = [1 if x == HIGH_LABEL else 0 for x in labels]
    n = len(ys)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = 0.0
    if denom:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom

    trend = slope * 100.0
    trend_label = f"NGHIÊNG {HIGH_LABEL}" if trend > 0.08 else f"NGHIÊNG {LOW_LABEL}" if trend < -0.08 else "TRUNG TÍNH"
    reversals = sum(1 for i in range(1, n) if ys[i] != ys[i - 1])
    reversal_rate = reversals / max(1, n - 1)
    smoothness = 1.0 - reversal_rate
    max_streak = 1
    cur = 1
    for i in range(1, n):
        if ys[i] == ys[i - 1]:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 1
    last_5 = ys[-5:] if n >= 5 else ys[:]
    prev_5 = ys[-10:-5] if n >= 10 else ys[:-5] if n > 5 else []
    return {
        "trend": trend,
        "trend_label": trend_label,
        "reversal_rate": reversal_rate,
        "smoothness": smoothness,
        "max_streak": max_streak,
        "last_value": ys[-1],
        "last_5_high": safe_div(sum(last_5), len(last_5)) if last_5 else 0.5,
        "prev_5_high": safe_div(sum(prev_5), len(prev_5)) if prev_5 else 0.5,
    }


def build_relearn_snapshot(report: Dict[str, Any], adv: Dict[str, Any]) -> str:
    patterns = report.get("patterns", [])[:3]
    top = " / ".join(p.get("name", "") for p in patterns) if patterns else "TRUNG TÍNH"
    return (
        f"Cầu: {top} | Cấu trúc: {report.get('structure', '-')} | "
        f"Chi tiết: {report.get('detail', '-')} | Tổng: {report.get('total', 0)} | "
        f"Mượt: {adv.get('smoothness', 0.0):.2f} | Nhiễu: {report.get('volatility', 0.0):.2f}"
    )


def enter_loss_cooldown(state: Dict[str, Any], report: Dict[str, Any], adv: Dict[str, Any]) -> bool:
    if state.get("cooldown_active"):
        return False
    state["cooldown_active"] = True
    state["cooldown_reason"] = f"Thua chuỗi {LOSS_STREAK_LIMIT} liên tiếp"
    state["last_relearn_note"] = f"Tự học lại từ đầu bộ lịch sử sau chuỗi thua {LOSS_STREAK_LIMIT}"
    state["last_note"] = state["last_relearn_note"]
    state["last_relearn_snapshot"] = build_relearn_snapshot(report, adv)
    state["last_relearn_total"] = int(report.get("total", 0))
    state["model_accuracy"] = {"pattern": 50, "structure": 50}
    state["last_model_predictions"] = {}
    state["last_gate_status"] = "TẠM DỪNG"
    state["last_gate_reason"] = state["cooldown_reason"]
    return True


def clear_loss_cooldown(state: Dict[str, Any]) -> bool:
    if not state.get("cooldown_active"):
        return False
    if int(state.get("current_wrong_streak", 0)) != 0:
        return False
    state["cooldown_active"] = False
    state["cooldown_reason"] = ""
    state["last_resume_note"] = "Đã có tín hiệu đúng, mở lại phân tích"
    state["last_note"] = state["last_resume_note"]
    return True


def pattern_signature(pattern: Dict[str, Any]) -> str:
    return f"{pattern.get('name','')}|{pattern.get('hint','')}|{int(pattern.get('score',0))}"


def update_confirm_state(state: Dict[str, Any], report: Dict[str, Any]) -> Tuple[bool, str]:
    patterns = report.get("patterns", [])
    if not patterns:
        state["pattern_confirm_sig"] = ""
        state["pattern_confirm_count"] = 0
        return False, "Chưa có cầu rõ ràng để xác nhận"

    top = patterns[0]
    sig = pattern_signature(top)
    score = int(top.get("score", 0))
    total = int(report.get("total", 0))

    need_wait = False
    reason = ""

    if score < CONFIRM_NEW_PATTERN_MIN_SCORE and total >= 8:
        need_wait = True
        if state.get("pattern_confirm_sig") != sig:
            state["pattern_confirm_sig"] = sig
            state["pattern_confirm_count"] = 1
        else:
            state["pattern_confirm_count"] = int(state.get("pattern_confirm_count", 0)) + 1

        if state["pattern_confirm_count"] < 2:
            reason = f"Đang bắt nhịp mới: {top.get('name','-')} ({score}%), đợi thêm 1 mẫu"
        else:
            need_wait = False
            reason = f"Đã xác nhận nhịp mới: {top.get('name','-')} ({score}%)"
    else:
        if state.get("pattern_confirm_sig") != sig:
            state["pattern_confirm_sig"] = sig
            state["pattern_confirm_count"] = 1
        else:
            state["pattern_confirm_count"] = int(state.get("pattern_confirm_count", 0)) + 1
        reason = f"Cầu rõ: {top.get('name','-')} ({score}%)"

    return need_wait, reason


def prediction_gate(labels: List[str], report: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    if state and state.get("cooldown_active"):
        if int(state.get("current_wrong_streak", 0)) == 0:
            return True, "Đã thoát chế độ học lại"
        return False, str(state.get("cooldown_reason") or f"Đang tự học lại sau chuỗi thua {LOSS_STREAK_LIMIT}")

    total = int(report.get("total", 0))
    patterns = report.get("patterns", [])
    top_name = str(patterns[0].get("name", "")) if patterns else ""
    top_score = int(patterns[0].get("score", 0)) if patterns else 0

    if state is not None:
        need_wait, wait_reason = update_confirm_state(state, report)
        if need_wait:
            return False, wait_reason

    if total < MIN_PREDICTION_DATA:
        if total >= 8 and top_score >= CLEAR_PATTERN_MIN_SCORE and top_name:
            return True, f"Cầu sớm: {top_name} ({top_score}%)"
        return False, f"Chưa đủ {MIN_PREDICTION_DATA} dữ liệu"

    if not patterns:
        return False, "Không có cầu rõ ràng để phân tích"

    if top_score < CLEAR_PATTERN_MIN_SCORE:
        if total >= 10 and top_score >= max(72, CLEAR_PATTERN_MIN_SCORE - 10):
            return True, f"Cầu sớm: {top_name} ({top_score}%)"
        return False, f"Cầu chưa đủ rõ: {top_name} ({top_score}%)"

    return True, f"Cầu rõ: {top_name} ({top_score}%)"


def predict_pattern(labels: List[str], report: Dict[str, Any]) -> Dict[str, Any]:
    patterns = report.get("patterns", [])
    if patterns:
        primary = patterns[0]
        hint = primary.get("hint")
        name = primary.get("name", "")
        if hint in (LOW_LABEL, HIGH_LABEL) and name in {
            "BỆT", "XEN KẼ", "1-1", "2-2", "XEN KẼ SÂU",
            "LẶP KHỐI 1", "LẶP KHỐI 2", "LẶP KHỐI 3",
            "LẶP MẪU 2", "LẶP MẪU 3", "LẶP MẪU 4", "LẶP MẪU 5", "LẶP MẪU 6", "LẶP MẪU 7", "LẶP MẪU 8",
            "CẦU 1-1", "CẦU 2-1", "CẦU 1-2", "CẦU 2-2", "CẦU 3-1", "CẦU 1-3", "CẦU 3-2", "CẦU 2-3", "CẦU 3-3",
            "NGHIÊNG", "NGHIÊNG NHẸ", "XU HƯỚNG", "ĐẢO CHIỀU"
        }:
            return {"label": hint, "confidence": min(95, int(primary.get("score", 60)) + 2), "source": f"pattern:{name}"}

    if len(labels) < 4:
        return {"label": labels[-1] if labels else LOW_LABEL, "confidence": 50, "source": "pattern"}
    if labels[-1] == labels[-2] == labels[-3]:
        return {"label": labels[-1], "confidence": 66, "source": "pattern"}
    if labels[-1] != labels[-2]:
        return {"label": labels[-2], "confidence": 56, "source": "pattern"}
    return {"label": labels[-1], "confidence": 54, "source": "pattern"}


def predict_structure(labels: List[str], report: Dict[str, Any]) -> Dict[str, Any]:
    patterns = report.get("patterns", [])
    if patterns:
        top = patterns[0]
        hint = top.get("hint")
        name = top.get("name", "")
        strong_same = {"BỆT", "BỆT SỚM", "LẶP MẪU 1", "LẶP KHỐI 1", "XEN KẼ SỚM", "XEN KẼ", "XEN KẼ SÂU", "1-1", "2-2"}
        if hint in (LOW_LABEL, HIGH_LABEL) and name in strong_same:
            return {"label": hint, "confidence": min(95, int(top.get("score", 60)) + 1), "source": f"structure:{name}"}
        if name.startswith("CẦU ") or name.startswith("LẶP MẪU") or name.startswith("LẶP KHỐI"):
            return {
                "label": hint if hint in (LOW_LABEL, HIGH_LABEL) else (labels[-1] if labels else LOW_LABEL),
                "confidence": min(92, int(top.get("score", 60)) + 1),
                "source": f"structure:{name}",
            }
        if name == "CÂN BẰNG SỚM":
            return {"label": labels[-1] if labels else LOW_LABEL, "confidence": 52, "source": "structure:balance"}

    if len(labels) < 2:
        return {"label": labels[-1] if labels else LOW_LABEL, "confidence": 50, "source": "structure"}
    return {"label": labels[-1], "confidence": 54, "source": "structure"}



def predict_chart(labels: List[str], report: Dict[str, Any], adv: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lớp chart AI: đọc độ dốc, độ mượt, tần suất đảo chiều và nhịp 5 mẫu gần nhất
    để đưa ra tín hiệu từ chính biểu đồ chuỗi Tài/Xỉu.
    """
    if not labels:
        return {"label": LOW_LABEL, "confidence": 50, "source": "chart"}

    trend = float(adv.get("trend", 0.0))
    trend_label = str(adv.get("trend_label", "TRUNG TÍNH"))
    smoothness = float(adv.get("smoothness", 0.0))
    reversal_rate = float(adv.get("reversal_rate", 0.0))
    last_5_high = float(adv.get("last_5_high", 0.5))
    prev_5_high = float(adv.get("prev_5_high", 0.5))
    momentum = float(adv.get("momentum", 0.0))
    last_label = labels[-1]

    # Điểm dựa trên xu hướng tổng thể của chart
    if trend > 0.10 or (last_5_high - prev_5_high) >= 0.15 or momentum > 0.08:
        label = HIGH_LABEL
        base = 62
        if trend > 0.20:
            base += 10
        if last_5_high > 0.60:
            base += 8
        if smoothness >= 0.60:
            base += 4
        if reversal_rate < 0.35:
            base += 4
    elif trend < -0.10 or (prev_5_high - last_5_high) >= 0.15 or momentum < -0.08:
        label = LOW_LABEL
        base = 62
        if trend < -0.20:
            base += 10
        if last_5_high < 0.40:
            base += 8
        if smoothness >= 0.60:
            base += 4
        if reversal_rate < 0.35:
            base += 4
    else:
        # chart đi ngang: bám theo trạng thái gần nhất nhưng confidence thấp
        label = last_label
        base = 52
        if trend_label != "TRUNG TÍNH":
            base += 3
        if 0.40 <= last_5_high <= 0.60:
            base += 2

    if trend_label == f"NGHIÊNG {HIGH_LABEL}" and label == HIGH_LABEL:
        base += 4
    if trend_label == f"NGHIÊNG {LOW_LABEL}" and label == LOW_LABEL:
        base += 4

    confidence = max(50, min(95, int(base)))
    return {
        "label": label,
        "confidence": confidence,
        "source": "chart",
    }


def update_model_accuracy(state: Dict[str, Any], predictions: Dict[str, Dict[str, Any]], actual: str) -> None:
    state.setdefault("model_accuracy", {"pattern": 50, "structure": 50})
    for name, pred in predictions.items():
        old = int(state["model_accuracy"].get(name, 50))
        old = old + 1 if pred.get("label") == actual else old - 1
        state["model_accuracy"][name] = max(1, min(99, old))


def update_prediction_feedback(state: Dict[str, Any], actual_label: str) -> None:
    pred = state.get("last_prediction_label")
    if pred not in (LOW_LABEL, HIGH_LABEL):
        return

    state["prediction_total"] = int(state.get("prediction_total", 0)) + 1
    if pred == actual_label:
        state["prediction_hits"] = int(state.get("prediction_hits", 0)) + 1
        state["last_prediction_result"] = "ĐÚNG"
        state["current_correct_streak"] = int(state.get("current_correct_streak", 0)) + 1
        state["current_wrong_streak"] = 0
        state["max_correct_streak"] = max(int(state.get("max_correct_streak", 0)), int(state["current_correct_streak"]))
    else:
        state["prediction_misses"] = int(state.get("prediction_misses", 0)) + 1
        state["last_prediction_result"] = "SAI"
        state["current_wrong_streak"] = int(state.get("current_wrong_streak", 0)) + 1
        state["current_correct_streak"] = 0
        state["max_wrong_streak"] = max(int(state.get("max_wrong_streak", 0)), int(state["current_wrong_streak"]))


def meta_decision(predictions: Dict[str, Dict[str, Any]], state: Dict[str, Any], report: Dict[str, Any], adv: Dict[str, Any]) -> Dict[str, Any]:
    model_acc = state.get("model_accuracy", {})
    vote: Dict[str, float] = defaultdict(float)
    model_scores: Dict[str, float] = {}

    strong_patterns = {
        "BỆT", "BỆT SỚM", "XEN KẼ", "XEN KẼ SỚM", "XEN KẼ SÂU",
        "1-1", "2-2", "LẶP KHỐI 1", "LẶP MẪU 2",
        "CẦU 1-1", "CẦU 2-1", "CẦU 1-2", "CẦU 2-2", "CẦU 3-1",
        "CẦU 1-3", "CẦU 2-3", "CẦU 3-2", "CẦU 3-3",
        "NGHIÊNG", "NGHIÊNG NHẸ", "XU HƯỚNG", "ĐẢO CHIỀU",
    }

    volatility = float(report.get("volatility", 0.0))
    smoothness = float(adv.get("smoothness", 0.0))
    reversal_rate = float(adv.get("reversal_rate", 0.0))
    entropy = float(report.get("entropy", 0.0))
    trend = float(adv.get("trend", 0.0))
    last_5_high = float(adv.get("last_5_high", 0.5))
    prev_5_high = float(adv.get("prev_5_high", 0.5))

    for name, pred in predictions.items():
        label = pred.get("label")
        conf = float(pred.get("confidence", 50))
        acc = float(model_acc.get(name, 50))
        score = conf * (0.85 + acc / 120.0)
        score *= 1.05 if name == "pattern" else 1.02 if name == "structure" else 1.0
        if name == "chart":
            if abs(trend) >= 0.18:
                score *= 1.10
            elif abs(trend) >= 0.10:
                score *= 1.05
            if abs(last_5_high - prev_5_high) >= 0.15:
                score *= 1.07
        if report.get("structure") in strong_patterns:
            score *= 1.08
        if smoothness >= 0.70:
            score *= 1.04
        elif reversal_rate >= 0.45:
            score *= 0.92
        if volatility > 0.80:
            score *= 0.90
        elif entropy < 1.0:
            score *= 1.03
        model_scores[name] = score
        vote[label] += score

    if not vote:
        return {"model": "none", "final_label": LOW_LABEL, "confidence": 50, "scores": {}}

    best_label = max(vote, key=vote.get)
    total = sum(vote.values())
    top = vote[best_label]
    top_ratio = top / total if total else 0.5
    agreement = sum(1 for p in predictions.values() if p.get("label") == best_label)
    strongest_conf = max((int(p.get("confidence", 50)) for p in predictions.values()), default=50)

    confidence = int(46 + top_ratio * 40 + (agreement - 1) * 4 + (strongest_conf - 50) * 0.15)
    if report.get("structure") in {"CÂN BẰNG", "TRUNG TÍNH", "CHƯA ĐỦ DỮ LIỆU"}:
        confidence -= 6
    if abs(trend) >= 0.18:
        confidence += 2

    confidence = max(0, min(confidence, 95))
    best_model = max(model_scores, key=model_scores.get)
    return {"model": best_model, "final_label": best_label, "confidence": confidence, "scores": dict(vote)}


def analyze_state_from_labels(state: Dict[str, Any], labels: List[str]) -> Dict[str, Any]:
    report = build_report(labels)
    adv = advanced_metrics(labels)
    chart_features = extract_chart_features(labels)
    adv.update(chart_features)

    resumed = False
    if state.get("cooldown_active") and int(state.get("current_wrong_streak", 0)) == 0:
        resumed = clear_loss_cooldown(state)

    relearned = False
    if int(state.get("current_wrong_streak", 0)) >= LOSS_STREAK_LIMIT and not state.get("cooldown_active", False):
        relearned = enter_loss_cooldown(state, report, adv)

    allowed, reason = prediction_gate(labels, report, state)
    state["last_gate_status"] = "CHO PHÉP" if allowed else "TẠM DỪNG"
    state["last_gate_reason"] = reason
    state["last_structure"] = report["structure"]
    state["last_detected_pattern"] = report["patterns"][0]["name"] if report.get("patterns") else ""
    state["last_detected_hint"] = report["patterns"][0].get("hint") if report.get("patterns") else None

    if not allowed:
        state["last_prediction_label"] = None
        state["last_prediction_conf"] = 0
        state["last_prediction_result"] = "TẠM DỪNG"
        state["last_note"] = reason
        state["last_model_predictions"] = {}
        return {"report": report, "adv": adv, "chart_features": chart_features,
                "predictions": {}, "meta": {}, "allowed": False, "reason": reason,
                "relearned": relearned, "resumed": resumed}

    predictions = {
        "pattern": predict_pattern(labels, report),
        "structure": predict_structure(labels, report),
        "chart": predict_chart(labels, report, adv),
    }
    meta = meta_decision(predictions, state, report, adv)
    state["last_prediction_label"] = meta["final_label"]
    state["last_prediction_conf"] = meta["confidence"]
    state["last_note"] = f"Model: {meta['model']}"
    state["last_structure"] = report["structure"]
    state["last_chart_label"] = predictions.get("chart", {}).get("label", "")
    state["last_chart_conf"] = int(predictions.get("chart", {}).get("confidence", 0))
    state["last_mode"] = "READY" if len(labels) >= MIN_ANALYSIS_LEN else "NORMAL"
    state["last_model_predictions"] = predictions
    state["last_prediction_result"] = "CHỜ KẾT QUẢ"

    return {"report": report, "adv": adv, "chart_features": chart_features, "predictions": predictions,
            "meta": meta, "allowed": True, "reason": reason, "relearned": relearned, "resumed": resumed}


def build_chart_summary(report: Dict[str, Any], adv: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> str:
    cooldown_text = "ĐANG HỌC LẠI" if state and state.get("cooldown_active") else "BÌNH THƯỜNG"
    return (
        f"Tổng: {report.get('total',0)} | {LOW_LABEL}: {report.get('low',0)} | {HIGH_LABEL}: {report.get('high',0)}\n"
        f"Cấu trúc: {report.get('structure','-')}\n"
        f"Chi tiết: {report.get('detail','-')}\n"
        f"Bệt max: {adv.get('max_streak',0)} | 10 gần: {adv.get('r10_high',0.5)*100:.1f}% {HIGH_LABEL} | "
        f"20 gần: {adv.get('r20_high',0.5)*100:.1f}% {HIGH_LABEL}\n"
        f"Momentum: {adv.get('momentum',0.0):.2f} | Trend: {adv.get('trend_label','TRUNG TÍNH')} ({adv.get('trend',0.0):.2f})\n"
        f"Mượt: {adv.get('smoothness',0.0):.2f} | Đảo chiều: {adv.get('reversal',0.0):.1f}%\n"
        f"Entropy: {report.get('entropy',0.0):.2f} | Volatility: {report.get('volatility',0.0):.2f}\n"
        f"Chart: {adv.get('trend_label','TRUNG TÍNH')} | {adv.get('trend',0.0):.2f} | Smooth: {adv.get('smoothness',0.0):.2f}\n"
        f"Chế độ: {cooldown_text}"
    )


def _point_color(label: str) -> str:
    return "gold" if label == HIGH_LABEL else "white"


def _point_edge(label: str) -> str:
    return "#3a2b00" if label == HIGH_LABEL else "#444444"


def build_bridge_chart_image(labels: List[str], report: Dict[str, Any], adv: Dict[str, Any], state: Optional[Dict[str, Any]] = None, limit: int = 0) -> Optional[BytesIO]:
    tail = labels[-limit:] if limit and len(labels) > limit else labels[:]
    if not tail:
        return None
    xs = list(range(1, len(tail) + 1))
    ys = [1 if x == HIGH_LABEL else 0 for x in tail]

    fig_w = max(14.0, min(38.0, 0.25 * len(tail) + 10.0))
    fig_h = 7.8 if len(tail) < 120 else 8.4
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=180)
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#11151c")

    for i in range(1, len(xs) + 1):
        ax.axvline(i, color="white", alpha=0.05, linewidth=0.8, zorder=0)
    ax.axhline(0, color="white", alpha=0.05, linewidth=0.8, zorder=0)
    ax.axhline(0.5, color="white", alpha=0.22, linewidth=1.2, linestyle="--", zorder=0)
    ax.axhline(1, color="white", alpha=0.05, linewidth=0.8, zorder=0)
    ax.axhspan(-0.02, 0.5, alpha=0.05, color="#ffffff", zorder=0)
    ax.axhspan(0.5, 1.02, alpha=0.05, color="#ffd700", zorder=0)

    ax.step(xs, ys, where="mid", linewidth=4.5, alpha=0.10, color="white", zorder=2)
    ax.step(xs, ys, where="mid", linewidth=2.8, alpha=0.18, color="#7db7ff", zorder=3)
    ax.step(xs, ys, where="mid", linewidth=2.0, alpha=0.95, color="#cfd8dc", zorder=4)
    ax.scatter(xs, ys, s=180, c=[_point_color(t) for t in tail], edgecolors=[_point_edge(t) for t in tail], linewidths=1.4, zorder=5)
    ax.scatter(xs, ys, s=80, c="none", edgecolors="black", linewidths=0.4, alpha=0.45, zorder=4)

    for x, y, t in zip(xs, ys, tail):
        txt_color = "#111111" if t == HIGH_LABEL else "#222222"
        ax.text(x, y, t, ha="center", va="center", fontsize=9, fontweight="bold", color=txt_color, zorder=6)

    if xs:
        ax.scatter([xs[-1]], [ys[-1]], s=320, c=["#ff4d4d"], edgecolors="white", linewidths=1.8, zorder=7)
        ax.text(xs[-1], ys[-1] + (0.11 if ys[-1] == 1 else -0.11), tail[-1], ha="center", va="center",
                fontsize=11, fontweight="bold", color="white", zorder=8)

    if len(ys) >= 5:
        for w, style, alpha, color in [(5, "--", 0.8, "#7db7ff"), (12, ":", 0.65, "#ffb347")]:
            if len(ys) >= w:
                ma = []
                for i in range(len(ys)):
                    start = max(0, i - w + 1)
                    seg = ys[start:i + 1]
                    ma.append(sum(seg) / len(seg))
                ax.plot(xs, ma, linewidth=1.5 if w == 5 else 1.8, alpha=alpha, linestyle=style, color=color, zorder=4)

    ax.set_ylim(-0.15, 1.15)
    ax.set_yticks([0, 1])
    ax.set_yticklabels([LOW_LABEL, HIGH_LABEL], fontsize=11, color="white")
    ax.set_xlabel("Mẫu gần nhất", fontsize=10, color="white")
    ax.set_ylabel("Trạng thái", fontsize=10, color="white")
    ax.set_title("BIỂU ĐỒ CẦU PHÂN TÍCH - TOÀN BỘ LỊCH SỬ", fontsize=13, fontweight="bold", color="white")

    if len(xs) <= 14:
        ax.set_xticks(xs)
        ax.set_xticklabels([str(i) for i in xs], fontsize=9, color="white")
    else:
        step = max(1, len(xs) // 12)
        ticks = xs[::step]
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(i) for i in ticks], fontsize=9, color="white")

    for spine in ax.spines.values():
        spine.set_color("#6b7280")
        spine.set_alpha(0.35)
    ax.tick_params(colors="white")
    ax.grid(True, axis="y", alpha=0.14, linestyle="-")

    ax.text(0.02, 0.98, build_chart_summary(report, adv, state), transform=ax.transAxes, va="top", ha="left",
            fontsize=9, color="white",
            bbox=dict(boxstyle="round,pad=0.55", facecolor="#121826", alpha=0.92, edgecolor="#44506a"))

    top_patterns = report.get("patterns", [])[:4]
    quick = " / ".join(p.get("name", "") for p in top_patterns) if top_patterns else "TRUNG TÍNH"
    ax.text(0.98, 0.02, f"Cầu: {quick}", transform=ax.transAxes, va="bottom", ha="right", fontsize=9, color="white",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#1f2937", alpha=0.9, edgecolor="#6b7280"))

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


async def send_bridge_chart(update: Update, labels: List[str], report: Dict[str, Any], adv: Dict[str, Any], title: str, state: Optional[Dict[str, Any]] = None) -> None:
    if not update.message:
        return
    chart = build_bridge_chart_image(labels, report, adv, state=state)
    if chart is None:
        await update.message.reply_text("📉 Chưa đủ dữ liệu để vẽ biểu đồ cầu.")
        return
    try:
        chart.seek(0)
        await update.message.reply_photo(photo=chart, caption=f"{title}\n{build_chart_summary(report, adv, state)}")
    except Exception as e:
        logger.exception("send_bridge_chart failed: %s", e)
        await update.message.reply_text("📉 Không thể gửi biểu đồ lúc này.")


def build_stats_message(report: Dict[str, Any], state: Dict[str, Any], adv: Dict[str, Any]) -> str:
    total = report["total"]
    low_p = safe_div(report["low"] * 100.0, total)
    high_p = safe_div(report["high"] * 100.0, total)

    patterns = report.get("patterns", [])[:4]
    pattern_lines = "\n".join(f"║ • {p['name']}: {p['detail']}" for p in patterns) if patterns else "║ • Chưa có cầu nổi bật"

    model_acc = state.get("model_accuracy", {})
    model_acc_line = f"P:{int(model_acc.get('pattern', 50))}% S:{int(model_acc.get('structure', 50))}%"
    cooldown_line = "ĐANG HỌC LẠI" if state.get("cooldown_active") else "BÌNH THƯỜNG"

    return (
        "╔════════════════════════════╗\n"
        "║      ✅ BẢNG THỐNG KÊ      ║\n"
        "╠════════════════════════════╣\n"
        f"║ Tổng    : {total}\n"
        f"║ {LOW_LABEL:<6}: {report['low']} ({low_p:.1f}%)\n"
        f"║ {HIGH_LABEL:<6}: {report['high']} ({high_p:.1f}%)\n"
        f"║ Cấu trúc: {report['structure']}\n"
        f"║ Chi tiết : {report['detail']}\n"
        f"║ Bệt max  : {adv.get('max_streak', 0)}\n"
        f"║ 10 gần   : {adv.get('r10_high', 0.5) * 100:.1f}% {HIGH_LABEL}\n"
        f"║ 20 gần   : {adv.get('r20_high', 0.5) * 100:.1f}% {HIGH_LABEL}\n"
        f"║ Momentum : {adv.get('momentum', 0.0):.2f}\n"
        f"║ Trend    : {adv.get('trend_label', 'TRUNG TÍNH')} ({adv.get('trend', 0.0):.2f})\n"
        f"║ Mượt     : {adv.get('smoothness', 0.0):.2f}\n"
        f"║ Nhiễu    : {adv.get('noise', 0.0):.2f}\n"
        f"║ Đảo chiều: {adv.get('reversal', 0.0):.1f}%\n"
        f"║ Entropy  : {report.get('entropy', 0.0):.2f}\n"
        f"║ Volatility: {report.get('volatility', 0.0):.2f}\n"
        f"║ Chính xác: {safe_div(state.get('prediction_hits', 0) * 100.0, state.get('prediction_total', 0)):.1f}%\n"
        f"║ Thắng    : {state.get('prediction_hits', 0)}\n"
        f"║ Thua     : {state.get('prediction_misses', 0)}\n"
        f"║ Tổng chốt: {state.get('prediction_total', 0)}\n"
        f"║ Chuỗi thắng max: {state.get('max_correct_streak', 0)}\n"
        f"║ Chuỗi thua  max: {state.get('max_wrong_streak', 0)}\n"
        f"║ M.Acc    : {model_acc_line}\n"
        f"║ Cửa gác  : {state.get('last_gate_status', 'CHỜ')}\n"
        f"║ Lý do    : {state.get('last_gate_reason', 'Chưa kiểm tra')}\n"
        f"║ Học lại  : {cooldown_line}\n"
        f"║ Lý do HL : {state.get('cooldown_reason') or '-'}\n"
        f"║ Ghi chú  : {state.get('last_relearn_note') or state.get('last_resume_note') or '-'}\n"
        f"║ Cầu hiện tại: {state.get('last_detected_pattern') or '-'}\n"
        f"║ Hướng    : {state.get('last_detected_hint') or '-'}\n"
        f"{pattern_lines}\n"
        "╚════════════════════════════╝"
    )


def build_analysis_message(report: Dict[str, Any], adv: Dict[str, Any], meta: Dict[str, Any], predictions: Dict[str, Dict[str, Any]]) -> str:
    warning = ""
    if adv.get("noise", 0.0) > 0.70:
        warning = "⚠️ Cầu nhiễu cao - nên thận trọng"
    elif adv.get("reversal", 0.0) > 25:
        warning = "⚠️ Có khả năng đảo chiều mạnh"

    top_patterns = report.get("patterns", [])[:4]
    pattern_text = " / ".join([p["name"] for p in top_patterns]) if top_patterns else "TRUNG TÍNH"
    chart_read = f"Tổng {report.get('total', 0)} | {LOW_LABEL} {report.get('low', 0)} | {HIGH_LABEL} {report.get('high', 0)} | Cấu trúc {report.get('structure', '-')}"

    return (
        "╔════════════════════════════╗\n"
        "║       🔍 PHÂN TÍCH CẦU     ║\n"
        "╠════════════════════════════╣\n"
        f"║ Nhìn chart: {chart_read}\n"
        f"║ Cầu chính : {pattern_text}\n"
        f"║ Detail    : {report.get('detail', '-')}\n"
        f"║ 10/20     : {adv.get('r10_high', 0.5) * 100:.1f}% / {adv.get('r20_high', 0.5) * 100:.1f}% {HIGH_LABEL}\n"
        f"║ Momentum  : {adv.get('momentum', 0.0):.2f}\n"
        f"║ Trend     : {adv.get('trend_label', 'TRUNG TÍNH')} ({adv.get('trend', 0.0):.2f})\n"
        f"║ Mượt      : {adv.get('smoothness', 0.0):.2f}\n"
        f"║ Nhiễu     : {adv.get('noise', 0.0):.2f}\n"
        f"║ Đảo chiều : {adv.get('reversal', 0.0):.1f}%\n"
        f"║ Pattern   : {predictions.get('pattern', {}).get('label', '-')} ({predictions.get('pattern', {}).get('confidence', 0)}%)\n"
        f"║ Struct    : {predictions.get('structure', {}).get('label', '-')} ({predictions.get('structure', {}).get('confidence', 0)}%)\n"
        f"║ Kết luận  : {meta.get('final_label', '-')}\n"
        f"║ Model     : {meta.get('model', '-')}\n"
        f"║ Tỷ lệ     : {meta.get('confidence', 0)}%\n"
        f"{warning}\n"
        "╚════════════════════════════╝"
    )


def build_final_message(meta: Dict[str, Any], state: Dict[str, Any]) -> str:
    return (
        f"CHỐT GỐC: {meta.get('final_label', '-')}\n"
        f"MODEL   : {meta.get('model', '-')}\n"
        f"TỶ LỆ   : {meta.get('confidence', 0)}%\n"
        f"THẮNG   : {state.get('prediction_hits', 0)}\n"
        f"THUA    : {state.get('prediction_misses', 0)}\n"
        f"TỔNG CHỐT: {state.get('prediction_total', 0)}\n"
        f"CHUỖI THẮNG MAX: {state.get('max_correct_streak', 0)}\n"
        f"CHUỖI THUA  MAX: {state.get('max_wrong_streak', 0)}\n"
    )


def build_stop_message(reason: str, report: Dict[str, Any], state: Dict[str, Any]) -> str:
    return (
        "╔════════════════════════════╗\n"
        "║        ⏸ BOT TẠM DỪNG     ║\n"
        "╠════════════════════════════╣\n"
        f"║ Lý do   : {reason}\n"
        f"║ Cấu trúc: {report.get('structure', '-')}\n"
        f"║ Chi tiết : {report.get('detail', '-')}\n"
        f"║ Tổng    : {report.get('total', 0)}\n"
        f"║ Trạng thái: {'Đang học lại' if state.get('cooldown_active') else 'Bình thường'}\n"
        "╚════════════════════════════╝"
    )


def build_relearn_message(report: Dict[str, Any], adv: Dict[str, Any], state: Dict[str, Any]) -> str:
    return (
        "╔════════════════════════════╗\n"
        "║      🧠 TỰ HỌC LẠI         ║\n"
        "╠════════════════════════════╣\n"
        f"║ Chuỗi thua: {LOSS_STREAK_LIMIT}\n"
        f"║ Đã reset logic/model: Có\n"
        f"║ Tổng lịch sử: {report.get('total', 0)}\n"
        f"║ Cấu trúc   : {report.get('structure', '-')}\n"
        f"║ Chi tiết   : {report.get('detail', '-')}\n"
        f"║ Mượt       : {adv.get('smoothness', 0.0):.2f}\n"
        f"║ Nhiễu      : {report.get('volatility', 0.0):.2f}\n"
        f"║ Snapshot   : {state.get('last_relearn_snapshot') or '-'}\n"
        "╚════════════════════════════╝"
    )


def build_resume_message(state: Dict[str, Any]) -> str:
    return (
        "╔════════════════════════════╗\n"
        "║       ✅ MỞ LẠI CẦU        ║\n"
        "╠════════════════════════════╣\n"
        f"║ Trạng thái: {state.get('last_resume_note') or 'Đã hồi phục'}\n"
        f"║ Chuỗi thua: {state.get('current_wrong_streak', 0)}\n"
        f"║ Học lại   : {'TẮT' if not state.get('cooldown_active') else 'ĐANG BẬT'}\n"
        "╚════════════════════════════╝"
    )


def build_stage_message(step: int) -> str:
    return "✅ Bước 1: Đã cập nhật bảng thống kê." if step == 1 else "🔍 Bước 2: Đã phân tích cầu." if step == 2 else "🧠 Bước 3: Hoàn tất."


async def send_robot_status(update: Update, caption: str) -> Optional[Any]:
    if not update.message:
        return None
    ensure_robot_asset()
    try:
        with open(ROBOT_IMAGE_PATH, "rb") as f:
            return await update.message.reply_photo(photo=f, caption=caption)
    except Exception as e:
        logger.exception("send_robot_status failed: %s", e)
        await update.message.reply_text(caption)
        return None


async def send_robot_analysis_sequence(update: Update, meta: Dict[str, Any], state: Dict[str, Any]) -> None:
    msg = await send_robot_status(
        update,
        "🤖 ĐANG PHÂN TÍCH...\n⏳ Vui lòng chờ 5 giây để robot xác nhận cầu mới."
    )
    await asyncio.sleep(ROBOT_ANALYZE_DELAY)

    if msg:
        try:
            await msg.edit_caption(
                caption=(
                    f"✅ ĐÃ PHÂN TÍCH XONG\n"
                    f"🤖 Robot đã sẵn sàng\n"
                    f"Chốt: {meta.get('final_label', '-')}\n"
                    f"Tỷ lệ: {meta.get('confidence', 0)}%"
                )
            )
        except Exception as e:
            logger.exception("edit_caption failed: %s", e)

    try:
        await update.message.reply_text(
            "🤖 ROBOT XÁC NHẬN XONG\n"
            f"Chốt: {meta.get('final_label', '-')}\n"
            f"Tỷ lệ: {meta.get('confidence', 0)}%\n"
            f"Trạng thái: {state.get('last_gate_status', 'CHỜ')}"
        )
    except Exception:
        pass


async def process_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, nums: Optional[List[int]] = None) -> None:
    if not update.message:
        return

    chat_id = get_key(update)

    async with STATE_LOCK:
        state = repair_state(await load_state(chat_id))
        entries: List[Tuple[int, str]] = []

        if nums:
            for n in nums:
                entries.append((n, map_value(n)))

        if entries:
            await append_history(chat_id, entries)

        rows = await load_history_rows(chat_id, limit=HISTORY_ANALYSIS_LIMIT)
        full_values = [r[0] for r in rows]
        full_labels = [r[1] for r in rows]

        state["values"] = _safe_tail(full_values, RECENT_CACHE)
        state["labels"] = _safe_tail(full_labels, RECENT_CACHE)
        rebuild_counters_from_labels(state, full_labels)

        if entries:
            latest_actual = entries[-1][1]
            update_prediction_feedback(state, latest_actual)
            prev_predictions = state.get("last_model_predictions", {})
            if isinstance(prev_predictions, dict) and prev_predictions:
                update_model_accuracy(state, prev_predictions, latest_actual)
            clear_loss_cooldown(state)

        result = analyze_state_from_labels(state, full_labels)
        await save_state(chat_id, state)
        users[chat_id] = state
        trim_cache()

    report = result["report"]
    adv = result["adv"]

    await update.message.reply_text(build_stage_message(1))
    await send_bridge_chart(update, full_labels, report, adv, "📈 BIỂU ĐỒ CẦU - CẬP NHẬT MỚI", state)
    await update.message.reply_text(build_stats_message(report, state, adv))

    if result.get("relearned", False):
        await update.message.reply_text(build_relearn_message(report, adv, state))
    if result.get("resumed", False):
        await update.message.reply_text(build_resume_message(state))

    if not result.get("allowed", False):
        await update.message.reply_text(build_stop_message(result.get("reason", "Cầu chưa rõ"), report, state))
        return

    meta = result["meta"]
    predictions = result["predictions"]

    await update.message.reply_text(build_stage_message(2))
    await send_robot_analysis_sequence(update, meta, state)
    await send_bridge_chart(update, full_labels, report, adv, "📈 BIỂU ĐỒ CẦU - PHÂN TÍCH", state)
    await update.message.reply_text(build_analysis_message(report, adv, meta, predictions))
    await update.message.reply_text(build_final_message(meta, state))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📘 TRỢ GIÚP\n"
        f"/stats - xem bảng thống kê\n"
        f"/ai - phân tích cầu\n"
        f"/next - giống /ai\n"
        f"/reset - xóa dữ liệu chat hiện tại\n"
        f"/factory_reset - xóa sạch toàn bộ bot\n\n"
        f"Quy đổi: số >= {THRESHOLD} -> {HIGH_LABEL}, số < {THRESHOLD} -> {LOW_LABEL}.\n"
        f"Khi thua {LOSS_STREAK_LIMIT} liên tiếp, bot sẽ tạm dừng, tự reset logic và học lại từ đầu lịch sử.\n"
        f"Luồng hoạt động: cập nhật thống kê → đọc biểu đồ → robot phân tích → kết quả chốt."
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = get_key(update)
    state = repair_state(await load_state(chat_id, force_reload=True))
    rows = await load_history_rows(chat_id, limit=HISTORY_ANALYSIS_LIMIT)
    labels = [r[1] for r in rows]
    state["labels"] = _safe_tail(labels, RECENT_CACHE)
    rebuild_counters_from_labels(state, labels)
    report = build_report(labels)
    adv = advanced_metrics(labels)
    adv.update(extract_chart_features(labels))
    await send_bridge_chart(update, labels, report, adv, "📈 BIỂU ĐỒ CẦU - THỐNG KÊ MỚI NHẤT", state)
    await update.message.reply_text(build_stats_message(report, state, adv))


async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = get_key(update)

    async with STATE_LOCK:
        state = repair_state(await load_state(chat_id, force_reload=True))
        rows = await load_history_rows(chat_id, limit=HISTORY_ANALYSIS_LIMIT)
        labels = [r[1] for r in rows]
        state["labels"] = _safe_tail(labels, RECENT_CACHE)
        rebuild_counters_from_labels(state, labels)
        clear_loss_cooldown(state)
        result = analyze_state_from_labels(state, labels)
        await save_state(chat_id, state)
        users[chat_id] = state
        trim_cache()

    report = result["report"]
    adv = result["adv"]

    await update.message.reply_text(build_stage_message(1))
    await send_bridge_chart(update, labels, report, adv, "📈 BIỂU ĐỒ CẦU - DÙNG CHO PHÂN TÍCH", state)
    await update.message.reply_text(build_stats_message(report, state, adv))

    if result.get("relearned", False):
        await update.message.reply_text(build_relearn_message(report, adv, state))
    if result.get("resumed", False):
        await update.message.reply_text(build_resume_message(state))

    if not result.get("allowed", False):
        await update.message.reply_text(build_stop_message(result.get("reason", "Cầu chưa rõ"), report, state))
        return

    meta = result["meta"]
    predictions = result["predictions"]

    await update.message.reply_text(build_stage_message(2))
    await send_robot_analysis_sequence(update, meta, state)
    await update.message.reply_text(build_analysis_message(report, adv, meta, predictions))
    await update.message.reply_text(build_final_message(meta, state))


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ai_cmd(update, context)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = get_key(update)

    def _work():
        with db_connect() as conn:
            conn.execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM chat_state WHERE chat_id = ?", (chat_id,))
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)

    users.pop(chat_id, None)
    await update.message.reply_text("🔄 Đã reset chat hiện tại.")


async def factory_reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    def _work():
        with db_connect() as conn:
            conn.execute("DELETE FROM history")
            conn.execute("DELETE FROM chat_state")
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)

    users.clear()
    await update.message.reply_text("🧼 Đã xóa sạch toàn bộ dữ liệu.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        nums = parse_input(update.message.text)
        if not nums:
            return
        await process_chat(update, context, nums)
    except Exception as e:
        logger.exception("handle_text failed: %s", e)
        if update.message:
            await update.message.reply_text("❌ Lỗi khi xử lý dữ liệu")


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Global error: %s", context.error)
    err = context.error
    if isinstance(err, RetryAfter):
        await asyncio.sleep(err.retry_after + 1)
    elif isinstance(err, (TimedOut, NetworkError, TelegramError)):
        await asyncio.sleep(1.0)
    try:
        if getattr(update, "message", None):
            await update.message.reply_text("⚠️ Có lỗi tạm thời, bot đã tự giữ an toàn.")
    except Exception:
        pass


def main():
    init_db()
    ensure_robot_asset()
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(False).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("ai", ai_cmd))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("factory_reset", factory_reset_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🔥 BOT THỐNG KÊ - PHÂN TÍCH CẦU ĐANG CHẠY...")
    app.run_polling(drop_pending_updates=True)


def run_bot_forever():
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.exception("Bot crashed, restarting in 5s: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    run_bot_forever()
