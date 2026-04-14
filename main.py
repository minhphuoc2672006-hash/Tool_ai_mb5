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
from typing import Dict, List, Optional, Tuple

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# =========================
# ENV
# =========================
def load_env() -> None:
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_env()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0").strip()

try:
    ADMIN_ID = int(ADMIN_ID_RAW or "0")
except ValueError as exc:
    raise RuntimeError("ADMIN_ID trong .env phải là số nguyên") from exc

if not BOT_TOKEN:
    raise RuntimeError("Thiếu BOT_TOKEN trong file .env")
if not ADMIN_ID:
    raise RuntimeError("Thiếu ADMIN_ID trong file .env")

DATA_FILE = Path("brain_state.json")

# =========================
# CONFIG
# =========================
WARMUP_SAMPLES = int(os.getenv("WARMUP_SAMPLES", "10000"))
RANDOM_MODE = os.getenv("RANDOM_MODE", "1").strip().lower() not in {"0", "false", "off", "no"}
RANDOM_TRIGGER_CONFIDENCE = int(os.getenv("RANDOM_TRIGGER_CONFIDENCE", "58"))
GAN_DAM_WEIGHT = float(os.getenv("GAN_DAM_WEIGHT", "1.25"))

# =========================
# HELPERS
# =========================
def esc(text: str) -> str:
    return html.escape(str(text))

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.upper().strip()

def parse_label(text: str) -> Optional[str]:
    t = normalize_text(text)
    t = re.sub(r"\s+", " ", t)
    tokens = re.findall(r"[A-Z0-9]+", t)
    if not tokens:
        return None

    if tokens in (["A"], ["LABELA"], ["CLASSA"]):
        return "A"
    if tokens in (["B"], ["LABELB"], ["CLASSB"]):
        return "B"

    if tokens and tokens[0] in {"TAI", "T"}:
        return "A"
    if tokens and tokens[0] in {"XIU", "X"}:
        return "B"

    return None

def parse_pattern(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"(\d+)\s*-\s*(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))

def parse_input(text: str) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    return parse_label(text), parse_pattern(text)

def format_start_message() -> str:
    return (
        "🚀 <b>SEQUENCE ANALYZER</b>\n"
        "━━━━━━━━━━━━━━\n"
        "• Gửi <b>A</b> hoặc <b>B</b> để nhập kết quả\n"
        "• Gửi dạng <b>A 11</b> / <b>B 11</b> để gắn nhãn + số\n"
        "• Gửi <b>2-1</b> để kiểm tra mẫu\n"
        "• /status xem trạng thái\n"
        "• /reset để xóa trạng thái\n"
    )

def format_status_message(text: str) -> str:
    return (
        "📡 <b>TRẠNG THÁI BOT</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"<pre>{esc(text)}</pre>"
    )

def format_result_message(result: str, confidence: int, score: int, mode_tag: str) -> str:
    return (
        "🧠 <b>ANALYSIS</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🎯 <b>Kết luận:</b> <b>{esc(result)}</b>\n"
        f"📊 <b>Độ tin cậy:</b> <b>{confidence}%</b>\n"
        f"⚡ <b>Score:</b> <b>{score}</b>\n"
        f"🎲 <b>Mode:</b> <b>{esc(mode_tag)}</b>\n"
    )

# =========================
# STATE
# =========================
@dataclass
class PendingCase:
    text: str
    predicted: str
    confidence: int
    score: int
    pattern: Optional[Tuple[int, int]] = None
    used_random: bool = False

@dataclass
class BrainState:
    history: List[str] = field(default_factory=list)
    pending_case: Optional[PendingCase] = None

    prediction_count: int = 0
    feedback_count: int = 0
    streak_win: int = 0
    streak_loss: int = 0

    model_score: Dict[str, float] = field(default_factory=lambda: {
        "streak": 0.0,
        "flip": 0.0,
        "momentum": 0.0,
        "pattern": 0.0,
    })

    pattern_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    warmup_done: bool = False
    warmup_samples: int = WARMUP_SAMPLES

    def save(self) -> None:
        data = {
            "history": self.history[-2000:],
            "prediction_count": self.prediction_count,
            "feedback_count": self.feedback_count,
            "streak_win": self.streak_win,
            "streak_loss": self.streak_loss,
            "model_score": self.model_score,
            "pattern_stats": self.pattern_stats,
            "warmup_done": self.warmup_done,
            "warmup_samples": self.warmup_samples,
        }
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        if not DATA_FILE.exists():
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        self.history = list(data.get("history", []))
        self.prediction_count = int(data.get("prediction_count", 0))
        self.feedback_count = int(data.get("feedback_count", 0))
        self.streak_win = int(data.get("streak_win", 0))
        self.streak_loss = int(data.get("streak_loss", 0))
        self.model_score.update(data.get("model_score", {}))
        self.pattern_stats.update(data.get("pattern_stats", {}))
        self.warmup_done = bool(data.get("warmup_done", False))
        self.warmup_samples = int(data.get("warmup_samples", WARMUP_SAMPLES))

    def reset(self) -> None:
        self.history = []
        self.pending_case = None
        self.prediction_count = 0
        self.feedback_count = 0
        self.streak_win = 0
        self.streak_loss = 0
        self.model_score = {"streak": 0.0, "flip": 0.0, "momentum": 0.0, "pattern": 0.0}
        self.pattern_stats = {}
        self.warmup_done = False
        self.warmup_samples = WARMUP_SAMPLES
        self.save()

    def ensure_pattern_key(self, key: str) -> None:
        if key not in self.pattern_stats:
            self.pattern_stats[key] = {"win": 0, "lose": 0}

    def warmup(self) -> None:
        if self.warmup_done:
            return

        for _ in range(self.warmup_samples):
            a = random.choice(["A", "B"])
            b = random.choice(["A", "B"])
            c = random.choice(["A", "B"])
            seq = [a, b, c]
            self.history.extend(seq)

            # giả lập chấm mẫu ngắn
            self._update_pattern_internal("1-1", seq[-1])

        self.history = self.history[-2000:]
        self.warmup_done = True
        self.save()

    def _update_pattern_internal(self, pattern: str, actual: str) -> None:
        self.ensure_pattern_key(pattern)

        expected = self.predict_by_pattern(pattern)
        if expected is None:
            return

        if expected == actual:
            self.pattern_stats[pattern]["win"] += 1
            self.model_score["pattern"] = clamp(self.model_score["pattern"] + 0.02, -5.0, 5.0)
        else:
            self.pattern_stats[pattern]["lose"] += 1
            self.model_score["pattern"] = clamp(self.model_score["pattern"] - 0.02, -5.0, 5.0)

    def score_history_bias(self) -> float:
        if len(self.history) < 20:
            return 0.0
        last = self.history[-20:]
        a = last.count("A")
        b = last.count("B")
        return (a - b) / 20.0

    def predict_by_streak(self) -> str:
        if len(self.history) < 2:
            return random.choice(["A", "B"])
        tail = self.history[-3:]
        if len(tail) >= 2 and tail[-1] == tail[-2]:
            return "B" if tail[-1] == "A" else "A"
        return tail[-1]

    def predict_by_flip(self) -> str:
        if len(self.history) < 2:
            return random.choice(["A", "B"])
        return "B" if self.history[-1] == "A" else "A"

    def predict_by_momentum(self) -> str:
        bias = self.score_history_bias()
        if bias > 0.05:
            return "A"
        if bias < -0.05:
            return "B"
        return random.choice(["A", "B"])

    def predict_by_pattern(self, pattern: str) -> Optional[str]:
        try:
            x, y = map(int, pattern.split("-"))
        except Exception:
            return None
        n = x + y
        if len(self.history) < n:
            return None
        seq = self.history[-n:]

        # heuristic đơn giản: nếu phần đầu giống nhau và phần cuối đảo, dự đoán đảo tiếp
        if x == 1 and y == 1:
            if len(seq) >= 2 and seq[-1] != seq[-2]:
                return seq[-1]
            return self.predict_by_momentum()

        if x == 2 and y == 1 and len(seq) >= 3:
            if seq[0] == seq[1] and seq[2] != seq[1]:
                return seq[2]
            return self.predict_by_flip()

        if x == 3 and y == 1 and len(seq) >= 4:
            if seq[0] == seq[1] == seq[2] and seq[3] != seq[2]:
                return seq[3]
            return self.predict_by_flip()

        return self.predict_by_momentum()

    def random_server_model(self) -> str:
        # random có bias nhẹ, dùng như fallback
        return "A" if random.random() < 0.5 else "B"

    def combined_predict(self, pattern: Optional[Tuple[int, int]] = None) -> Tuple[str, int, int, bool, str]:
        preds = {
            "streak": self.predict_by_streak(),
            "flip": self.predict_by_flip(),
            "momentum": self.predict_by_momentum(),
        }

        if pattern is not None:
            ptxt = f"{pattern[0]}-{pattern[1]}"
            p_pred = self.predict_by_pattern(ptxt)
            if p_pred is not None:
                preds["pattern"] = p_pred

        weights = {
            "streak": 1.2 + self.model_score["streak"],
            "flip": 1.1 + self.model_score["flip"],
            "momentum": 1.3 + self.model_score["momentum"],
            "pattern": 1.4 + self.model_score["pattern"],
        }

        a_w = 0.0
        b_w = 0.0
        for name, pred in preds.items():
            w = max(0.1, weights.get(name, 1.0))
            if pred == "A":
                a_w += w
            else:
                b_w += w

        result = "A" if a_w >= b_w else "B"
        total = a_w + b_w
        confidence = int(round((max(a_w, b_w) / max(1e-9, total)) * 100))
        confidence = max(50, min(99, confidence))
        score = int(round((a_w - b_w) * 10))

        used_random = False
        mode_tag = "ENSEMBLE"

        if RANDOM_MODE and confidence <= RANDOM_TRIGGER_CONFIDENCE:
            used_random = True
            mode_tag = "RANDOM-FALLBACK"
            result = self.random_server_model()
            confidence = min(confidence, RANDOM_TRIGGER_CONFIDENCE)
            score = int(score * 0.5)

        return result, confidence, score, used_random, mode_tag

    def learn_feedback(self, actual: str, predicted: str, used_random: bool, pattern: Optional[Tuple[int, int]] = None) -> None:
        self.prediction_count += 1
        self.feedback_count += 1

        if pattern is not None:
            ptxt = f"{pattern[0]}-{pattern[1]}"
            self.ensure_pattern_key(ptxt)
            if predicted == actual:
                self.pattern_stats[ptxt]["win"] += 1
            else:
                self.pattern_stats[ptxt]["lose"] += 1

        # cập nhật trọng số chung
        if predicted == actual:
            self.streak_win += 1
            self.streak_loss = 0
            self.model_score["streak"] = clamp(self.model_score["streak"] + 0.03, -5.0, 5.0)
            self.model_score["flip"] = clamp(self.model_score["flip"] + 0.01, -5.0, 5.0)
            self.model_score["momentum"] = clamp(self.model_score["momentum"] + 0.02, -5.0, 5.0)
        else:
            self.streak_loss += 1
            self.streak_win = 0
            self.model_score["streak"] = clamp(self.model_score["streak"] - 0.03, -5.0, 5.0)
            self.model_score["flip"] = clamp(self.model_score["flip"] - 0.01, -5.0, 5.0)
            self.model_score["momentum"] = clamp(self.model_score["momentum"] - 0.02, -5.0, 5.0)

        if used_random:
            # random chỉ là fallback, không ép nó "thông minh hơn"
            self.model_score["pattern"] = clamp(self.model_score["pattern"] + (0.005 if predicted == actual else -0.005), -5.0, 5.0)

        self.history.append(actual)
        self.history = self.history[-5000:]
        self.save()

    def status_text(self) -> str:
        top_pattern = "N/A"
        if self.pattern_stats:
            best = sorted(
                self.pattern_stats.items(),
                key=lambda kv: (kv[1]["win"] / max(1, kv[1]["win"] + kv[1]["lose"])),
                reverse=True,
            )[0]
            w = best[1]["win"]
            l = best[1]["lose"]
            top_pattern = f"{best[0]} ({w}/{w+l})"

        lines = [
            f"Warmup done: {self.warmup_done}",
            f"Warmup samples: {self.warmup_samples}",
            f"History size: {len(self.history)}",
            f"Predictions: {self.prediction_count}",
            f"Feedback: {self.feedback_count}",
            f"Streak win: {self.streak_win}",
            f"Streak loss: {self.streak_loss}",
            f"Score streak: {self.model_score['streak']:+.2f}",
            f"Score flip: {self.model_score['flip']:+.2f}",
            f"Score momentum: {self.model_score['momentum']:+.2f}",
            f"Score pattern: {self.model_score['pattern']:+.2f}",
            f"Best pattern: {top_pattern}",
        ]
        return "\n".join(lines)

brain = BrainState()
LOCK = asyncio.Lock()

# =========================
# TELEGRAM COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if update.message:
        await update.message.reply_text(format_start_message(), parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if update.message:
        await update.message.reply_text(
            "📖 <b>HƯỚNG DẪN</b>\n"
            "━━━━━━━━━━━━━━\n"
            "• Gửi A/B để thêm kết quả\n"
            "• Gửi A 11 hoặc B 11 để gắn nhãn có số\n"
            "• Gửi 2-1, 3-1... để kiểm tra mẫu\n"
            "• /status xem trạng thái\n"
            "• /reset xóa toàn bộ dữ liệu",
            parse_mode="HTML",
        )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        if update.message:
            await update.message.reply_text(format_status_message(brain.status_text()), parse_mode="HTML")

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        brain.reset()
    if update.message:
        await update.message.reply_text("📦 <b>Đã reset sạch.</b>", parse_mode="HTML")

async def warmup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        brain.warmup()
    if update.message:
        await update.message.reply_text("✅ <b>Đã học xong dữ liệu khởi tạo.</b>", parse_mode="HTML")

# =========================
# MAIN HANDLER
# =========================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    async with LOCK:
        # input dạng: A 11 / B 11 / A / B
        label, pattern = parse_input(text)

        if label:
            # Nếu đang có ca dự đoán trước đó, thì dòng này là feedback
            if brain.pending_case is not None:
                pc = brain.pending_case
                brain.learn_feedback(
                    actual=label,
                    predicted=pc.predicted,
                    used_random=pc.used_random,
                    pattern=pc.pattern,
                )
                brain.pending_case = None
                await update.message.reply_text(
                    "✅ <b>Đã ghi nhận kết quả và cập nhật mô hình.</b>",
                    parse_mode="HTML",
                )
                return

            # Nếu chưa có pending case, vẫn lưu như lịch sử
            brain.history.append(label)
            brain.history = brain.history[-5000:]
            brain.save()

            if pattern is not None:
                ptxt = f"{pattern[0]}-{pattern[1]}"
                pred, conf, score, used_random, mode_tag = brain.combined_predict(pattern)
                brain.pending_case = PendingCase(
                    text=text,
                    predicted=pred,
                    confidence=conf,
                    score=score,
                    pattern=pattern,
                    used_random=used_random,
                )
                await update.message.reply_text(
                    format_result_message(pred, conf, score, mode_tag) + f"\n🧩 <b>Pattern:</b> <code>{esc(ptxt)}</code>",
                    parse_mode="HTML",
                )
                return

            await update.message.reply_text("✅ <b>Đã lưu kết quả.</b>", parse_mode="HTML")
            return

        # pattern only: 2-1 / 3-1 ...
        if pattern is not None:
            pred, conf, score, used_random, mode_tag = brain.combined_predict(pattern)
            brain.pending_case = PendingCase(
                text=text,
                predicted=pred,
                confidence=conf,
                score=score,
                pattern=pattern,
                used_random=used_random,
            )
            await update.message.reply_text(
                format_result_message(pred, conf, score, mode_tag) +
                f"\n🧩 <b>Pattern:</b> <code>{esc(f'{pattern[0]}-{pattern[1]}')}</code>",
                parse_mode="HTML",
            )
            return

        await update.message.reply_text(
            "❌ <b>Không hiểu dữ liệu.</b>\n"
            "Gửi A/B hoặc 2-1.",
            parse_mode="HTML",
        )

# =========================
# STARTUP
# =========================
def main():
    brain.load()
    brain.warmup()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("warmup", warmup_cmd))

    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle)
    )

    print("Bot đang chạy...")
    app.run_polling()

if __name__ == "__main__":
    main()
