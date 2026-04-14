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
DATA_FILE = Path("tai_xiu_state.json")

try:
    ADMIN_ID = int(ADMIN_ID_RAW or "0")
except ValueError as exc:
    raise RuntimeError("ADMIN_ID trong .env phải là số nguyên") from exc

if not BOT_TOKEN:
    raise RuntimeError("Thiếu BOT_TOKEN trong file .env")
if not ADMIN_ID:
    raise RuntimeError("Thiếu ADMIN_ID trong file .env")


# =========================
# CONFIG
# =========================
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "5000"))
WARMUP_SAMPLES = int(os.getenv("WARMUP_SAMPLES", "10000"))
WARMUP_ON_START = os.getenv("WARMUP_ON_START", "1").strip().lower() not in {"0", "false", "off", "no"}


# =========================
# HELPERS
# =========================
def esc(text: str) -> str:
    return html.escape(str(text))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").upper().strip()


def parse_result(text: str) -> Optional[str]:
    t = normalize_text(text)

    if re.search(r"\bTAI\b", t):
        return "TAI"
    if re.search(r"\bXIU\b", t):
        return "XIU"

    return None


def parse_pattern(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"(\d+)\s*-\s*(\d+)", text)
    if not m:
        return None

    x = int(m.group(1))
    y = int(m.group(2))
    if x <= 0 or y <= 0:
        return None

    return x, y


def pattern_key(p: Tuple[int, int]) -> str:
    return f"{p[0]}-{p[1]}"


def format_start_message() -> str:
    return (
        "🚀 <b>TÀI XỈU SEQUENCE ANALYZER</b>\n"
        "━━━━━━━━━━━━━━\n"
        "• Gửi <b>Tài</b> hoặc <b>Xỉu</b> để lưu kết quả\n"
        "• Gửi <b>2-1</b>, <b>3-1</b>, <b>2-2</b>... để phân tích cầu\n"
        "• Gửi <b>Tài 11 cầu 2-1</b> để vừa lưu kết quả vừa xem mẫu\n"
        "• /status xem trạng thái\n"
        "• /patterns xem các mẫu khớp nhiều nhất\n"
        "• /warmup để nạp dữ liệu mô phỏng\n"
        "• /reset xóa sạch dữ liệu\n"
    )


def format_status_message(text: str) -> str:
    return (
        "📡 <b>TRẠNG THÁI BOT</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"<pre>{esc(text)}</pre>"
    )


def format_pattern_message(title: str, detail: str) -> str:
    return (
        f"🧩 <b>{esc(title)}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"<pre>{esc(detail)}</pre>"
    )


# =========================
# ANALYSIS LOGIC
# =========================
def run_length(history: List[str]) -> int:
    if not history:
        return 0

    last = history[-1]
    n = 1
    for i in range(len(history) - 2, -1, -1):
        if history[i] == last:
            n += 1
        else:
            break
    return n


def matches_run_pattern(seq: List[str], x: int, y: int) -> bool:
    if len(seq) != x + y:
        return False

    first = seq[:x]
    second = seq[x:]

    if not first or not second:
        return False
    if len(set(first)) != 1:
        return False
    if len(set(second)) != 1:
        return False

    return first[0] != second[0]


# =========================
# STATE
# =========================
@dataclass
class PendingCase:
    pattern: Tuple[int, int]
    detail: str


@dataclass
class Brain:
    history: List[str] = field(default_factory=list)
    pending_case: Optional[PendingCase] = None

    total_tai: int = 0
    total_xiu: int = 0
    feedback_count: int = 0

    pattern_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    warmup_done: bool = False
    warmup_samples: int = WARMUP_SAMPLES

    def load(self) -> None:
        if not DATA_FILE.exists():
            return

        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        self.history = list(data.get("history", []))
        self.total_tai = int(data.get("total_tai", 0))
        self.total_xiu = int(data.get("total_xiu", 0))
        self.feedback_count = int(data.get("feedback_count", 0))
        self.pattern_stats = dict(data.get("pattern_stats", {}))
        self.warmup_done = bool(data.get("warmup_done", False))
        self.warmup_samples = int(data.get("warmup_samples", WARMUP_SAMPLES))

        self.history = [x for x in self.history if x in {"TAI", "XIU"}]
        self.history = self.history[-HISTORY_LIMIT:]

        self.total_tai = self.history.count("TAI")
        self.total_xiu = self.history.count("XIU")

    def save(self) -> None:
        data = {
            "history": self.history[-HISTORY_LIMIT:],
            "total_tai": self.total_tai,
            "total_xiu": self.total_xiu,
            "feedback_count": self.feedback_count,
            "pattern_stats": self.pattern_stats,
            "warmup_done": self.warmup_done,
            "warmup_samples": self.warmup_samples,
        }
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset(self) -> None:
        self.history = []
        self.pending_case = None
        self.total_tai = 0
        self.total_xiu = 0
        self.feedback_count = 0
        self.pattern_stats = {}
        self.warmup_done = False
        self.warmup_samples = WARMUP_SAMPLES
        self.save()

    def add_result(self, result: str) -> None:
        if result not in {"TAI", "XIU"}:
            return

        self.history.append(result)
        self.history = self.history[-HISTORY_LIMIT:]

        if result == "TAI":
            self.total_tai += 1
        else:
            self.total_xiu += 1

        self.save()

    def ensure_pattern(self, key: str) -> None:
        if key not in self.pattern_stats:
            self.pattern_stats[key] = {"seen": 0, "tai_after": 0, "xiu_after": 0}

    def warmup(self, n: int = WARMUP_SAMPLES) -> None:
        if n <= 0:
            self.warmup_done = True
            self.save()
            return

        # Sinh dữ liệu mô phỏng random để bot có lịch sử ban đầu.
        # Mục đích là thống kê / hiển thị cầu, không phải dự đoán.
        for _ in range(n):
            self.history.append(random.choice(["TAI", "XIU"]))

        self.history = self.history[-HISTORY_LIMIT:]
        self.total_tai = self.history.count("TAI")
        self.total_xiu = self.history.count("XIU")
        self.warmup_done = True
        self.save()

    def analyze_pattern(self, p: Tuple[int, int]) -> str:
        x, y = p
        need = x + y

        if len(self.history) < need + 1:
            return f"Chưa đủ dữ liệu để phân tích mẫu {pattern_key(p)}."

        seen = 0
        tai_after = 0
        xiu_after = 0

        for i in range(0, len(self.history) - need):
            window = self.history[i : i + need]
            if matches_run_pattern(window, x, y):
                seen += 1
                nxt = self.history[i + need]
                if nxt == "TAI":
                    tai_after += 1
                else:
                    xiu_after += 1

        key = pattern_key(p)
        self.ensure_pattern(key)
        self.pattern_stats[key]["seen"] += seen
        self.pattern_stats[key]["tai_after"] += tai_after
        self.pattern_stats[key]["xiu_after"] += xiu_after
        self.save()

        total_after = tai_after + xiu_after
        if total_after == 0:
            next_text = "Chưa có dữ liệu kết quả kế tiếp sau mẫu này."
        else:
            next_text = f"Sau mẫu này: Tài {tai_after} lần, Xỉu {xiu_after} lần."

        return (
            f"Mẫu {key}\n"
            f"- Xuất hiện: {seen} lần\n"
            f"- {next_text}"
        )

    def top_patterns_text(self) -> str:
        if not self.pattern_stats:
            return "Chưa có mẫu nào."

        items = []
        for k, v in self.pattern_stats.items():
            seen = v.get("seen", 0)
            tai_after = v.get("tai_after", 0)
            xiu_after = v.get("xiu_after", 0)
            total_after = tai_after + xiu_after

            if seen <= 0:
                continue

            dominant = max(tai_after, xiu_after) if total_after > 0 else 0
            rate = (dominant / total_after * 100.0) if total_after > 0 else 0.0
            items.append((rate, seen, k, tai_after, xiu_after))

        items.sort(reverse=True, key=lambda x: (x[0], x[1], x[2]))

        lines = []
        for rate, seen, k, tai_after, xiu_after in items[:10]:
            total_after = tai_after + xiu_after
            lines.append(
                f"{k}: seen={seen}, after={total_after}, Tài={tai_after}, Xỉu={xiu_after}, rate={rate:.1f}%"
            )

        return "\n".join(lines) if lines else "Chưa có mẫu nào."

    def status_text(self) -> str:
        last = self.history[-1] if self.history else "-"
        streak = run_length(self.history)
        last20 = self.history[-20:]
        tai20 = last20.count("TAI")
        xiu20 = last20.count("XIU")

        lines = [
            f"Warmup done: {self.warmup_done}",
            f"Warmup samples: {self.warmup_samples}",
            f"History size: {len(self.history)}",
            f"Total Tài: {self.total_tai}",
            f"Total Xỉu: {self.total_xiu}",
            f"Last result: {last}",
            f"Current streak: {streak}",
            f"Last 20 -> Tài: {tai20}, Xỉu: {xiu20}",
            f"Feedback count: {self.feedback_count}",
            f"Patterns saved: {len(self.pattern_stats)}",
        ]
        return "\n".join(lines)


brain = Brain()
LOCK = asyncio.Lock()


# =========================
# COMMANDS
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
            "• Gửi Tài / Xỉu để lưu kết quả\n"
            "• Gửi 2-1, 3-1, 2-2... để xem lịch sử khớp mẫu\n"
            "• Gửi Tài 11 cầu 2-1 cũng được, bot sẽ đọc Tài/Xỉu và mẫu 2-1\n"
            "• /status xem thống kê\n"
            "• /patterns xem top mẫu đã lưu\n"
            "• /warmup để nạp dữ liệu mô phỏng\n"
            "• /reset xóa sạch dữ liệu",
            parse_mode="HTML",
        )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        text = brain.status_text()
    if update.message:
        await update.message.reply_text(format_status_message(text), parse_mode="HTML")


async def patterns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        text = brain.top_patterns_text()
    if update.message:
        await update.message.reply_text(
            format_pattern_message("TOP MẪU", text),
            parse_mode="HTML",
        )


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        brain.reset()
    if update.message:
        await update.message.reply_text(
            "📦 <b>Đã reset sạch toàn bộ dữ liệu.</b>",
            parse_mode="HTML",
        )


async def warmup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    async with LOCK:
        brain.warmup()

    if update.message:
        await update.message.reply_text(
            f"✅ <b>Đã warmup xong {brain.warmup_samples:,} tay mô phỏng.</b>",
            parse_mode="HTML",
        )


# =========================
# HANDLER
# =========================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    async with LOCK:
        result = parse_result(text)
        pattern = parse_pattern(text)

        pattern_reply = None
        if pattern is not None:
            pattern_reply = brain.analyze_pattern(pattern)
            brain.pending_case = PendingCase(
                pattern=pattern,
                detail=pattern_reply,
            )

        if result is not None:
            brain.add_result(result)
            brain.feedback_count += 1

            if pattern is not None:
                await update.message.reply_text(
                    "✅ <b>Đã lưu kết quả và phân tích mẫu.</b>\n"
                    f"🧾 <b>Kết quả:</b> <b>{esc(result)}</b>\n"
                    f"🧩 <b>Mẫu:</b> <code>{esc(pattern_key(pattern))}</code>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"<pre>{esc(pattern_reply or '')}</pre>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"✅ <b>Đã lưu kết quả:</b> <b>{esc(result)}</b>",
                    parse_mode="HTML",
                )
            return

        if pattern is not None:
            await update.message.reply_text(
                "🧩 <b>PHÂN TÍCH MẪU</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"<pre>{esc(pattern_reply or '')}</pre>",
                parse_mode="HTML",
            )
            return

        await update.message.reply_text(
            "❌ <b>Không hiểu dữ liệu.</b>\n"
            "Gửi Tài / Xỉu hoặc nhập mẫu như 2-1, 3-1, 2-2...",
            parse_mode="HTML",
        )


# =========================
# MAIN
# =========================
def main() -> None:
    brain.load()

    if WARMUP_ON_START and not brain.history:
        brain.warmup(WARMUP_SAMPLES)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("patterns", patterns_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("warmup", warmup_cmd))

    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle)
    )

    print("Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
