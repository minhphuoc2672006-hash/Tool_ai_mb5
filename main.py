#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
DATA_FILE = Path("binary_tracker_state.json")

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
LABEL_A = os.getenv("LABEL_A", "A").strip().upper()
LABEL_B = os.getenv("LABEL_B", "B").strip().upper()


# =========================
# HELPERS
# =========================
def esc(text: str) -> str:
    return html.escape(str(text))


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").upper().strip()


def parse_label(text: str) -> Optional[str]:
    t = normalize_text(text)
    t = re.sub(r"\s+", " ", t)

    tokens = re.findall(r"[A-Z0-9]+", t)
    if not tokens:
        return None

    if tokens[0] in {LABEL_A, "A"}:
        return LABEL_A
    if tokens[0] in {LABEL_B, "B"}:
        return LABEL_B

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
        f"🚀 <b>BINARY TRACKER BOT</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"• Gửi <b>{LABEL_A}</b> hoặc <b>{LABEL_B}</b> để lưu kết quả\n"
        f"• Gửi <b>2-1</b>, <b>3-1</b>, <b>2-2</b>... để phân tích mẫu\n"
        f"• Gửi <b>{LABEL_A} 11 cầu 2-1</b> để lưu + phân tích\n"
        f"• /status xem trạng thái\n"
        f"• /patterns xem top mẫu\n"
        f"• /reset để xóa sạch dữ liệu\n"
        f"• /help xem hướng dẫn\n"
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


def format_saved_message(label: str, number: Optional[int]) -> str:
    if number is None:
        return f"✅ <b>Đã lưu:</b> <b>{esc(label)}</b>"
    return f"✅ <b>Đã lưu:</b> <b>{esc(label)} {number}</b>"


# =========================
# STATE
# =========================
@dataclass
class Entry:
    label: str
    number: Optional[int] = None
    pattern: Optional[str] = None


@dataclass
class Brain:
    history: List[Entry] = field(default_factory=list)
    pattern_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    feedback_count: int = 0

    def load(self) -> None:
        if not DATA_FILE.exists():
            return

        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return

        raw_history = data.get("history", [])
        fixed: List[Entry] = []
        if isinstance(raw_history, list):
            for item in raw_history:
                if isinstance(item, dict) and item.get("label") in {LABEL_A, LABEL_B}:
                    fixed.append(
                        Entry(
                            label=item["label"],
                            number=item.get("number"),
                            pattern=item.get("pattern"),
                        )
                    )

        self.history = fixed[-HISTORY_LIMIT:]
        self.pattern_stats = dict(data.get("pattern_stats", {}))
        self.feedback_count = int(data.get("feedback_count", 0))

    def save(self) -> None:
        data = {
            "history": [entry.__dict__ for entry in self.history[-HISTORY_LIMIT:]],
            "pattern_stats": self.pattern_stats,
            "feedback_count": self.feedback_count,
        }
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset(self) -> None:
        self.history = []
        self.pattern_stats = {}
        self.feedback_count = 0
        self.save()

    def add(self, label: str, number: Optional[int] = None, pattern: Optional[str] = None) -> None:
        if label not in {LABEL_A, LABEL_B}:
            return
        self.history.append(Entry(label=label, number=number, pattern=pattern))
        self.history = self.history[-HISTORY_LIMIT:]
        self.feedback_count += 1
        self.save()

    def result_list(self) -> List[str]:
        return [e.label for e in self.history]

    def run_length(self) -> int:
        if not self.history:
            return 0
        last = self.history[-1].label
        count = 1
        for e in reversed(self.history[:-1]):
            if e.label == last:
                count += 1
            else:
                break
        return count

    def matches_run_pattern(self, seq: List[str], x: int, y: int) -> bool:
        if len(seq) != x + y:
            return False
        a = seq[:x]
        b = seq[x:]
        return len(set(a)) == 1 and len(set(b)) == 1 and a[0] != b[0]

    def analyze_pattern(self, p: Tuple[int, int]) -> str:
        x, y = p
        need = x + y
        results = self.result_list()

        if len(results) < need + 1:
            return f"Chưa đủ dữ liệu để phân tích mẫu {pattern_key(p)}."

        seen = 0
        a_after = 0
        b_after = 0

        for i in range(0, len(results) - need):
            window = results[i : i + need]
            if self.matches_run_pattern(window, x, y):
                seen += 1
                nxt = results[i + need]
                if nxt == LABEL_A:
                    a_after += 1
                else:
                    b_after += 1

        key = pattern_key(p)
        stat = self.pattern_stats.get(key, {"seen": 0, "a_after": 0, "b_after": 0})
        stat["seen"] += seen
        stat["a_after"] += a_after
        stat["b_after"] += b_after
        self.pattern_stats[key] = stat
        self.save()

        total_after = a_after + b_after
        if total_after == 0:
            next_text = "Chưa có dữ liệu kết quả kế tiếp sau mẫu này."
        else:
            next_text = f"Sau mẫu này: {LABEL_A} {a_after} lần, {LABEL_B} {b_after} lần."

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
            seen = int(v.get("seen", 0))
            a_after = int(v.get("a_after", 0))
            b_after = int(v.get("b_after", 0))
            total_after = a_after + b_after
            if seen <= 0 or total_after <= 0:
                continue
            dominant = max(a_after, b_after)
            rate = dominant / total_after * 100.0
            items.append((rate, seen, k, a_after, b_after))

        items.sort(reverse=True, key=lambda x: (x[0], x[1], x[2]))

        lines = []
        for rate, seen, k, a_after, b_after in items[:10]:
            total_after = a_after + b_after
            lines.append(
                f"{k}: seen={seen}, after={total_after}, {LABEL_A}={a_after}, {LABEL_B}={b_after}, rate={rate:.1f}%"
            )

        return "\n".join(lines) if lines else "Chưa có mẫu nào."

    def status_text(self) -> str:
        last = self.history[-1] if self.history else None
        if last:
            if last.number is not None:
                last_text = f"{last.label} {last.number}"
            else:
                last_text = last.label
        else:
            last_text = "-"

        results = self.result_list()
        last20 = results[-20:]
        a20 = last20.count(LABEL_A)
        b20 = last20.count(LABEL_B)

        lines = [
            f"History size: {len(self.history)}",
            f"Last saved: {last_text}",
            f"Current streak: {self.run_length()}",
            f"Last 20 -> {LABEL_A}: {a20}, {LABEL_B}: {b20}",
            f"Feedback count: {self.feedback_count}",
            f"Patterns saved: {len(self.pattern_stats)}",
        ]
        return "\n".join(lines)


brain = Brain()
brain.load()
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
            f"• Gửi {LABEL_A} / {LABEL_B} để lưu kết quả\n"
            f"• Gửi {LABEL_A} 11 / {LABEL_B} 7 để lưu cả số\n"
            "• Gửi 2-1, 3-1, 2-2... để xem lịch sử khớp mẫu\n"
            f"• Gửi {LABEL_A} 11 cầu 2-1 cũng được\n"
            "• /status xem thống kê\n"
            "• /patterns xem top mẫu đã lưu\n"
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
        await update.message.reply_text(format_pattern_message("TOP MẪU", text), parse_mode="HTML")


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    async with LOCK:
        brain.reset()
    if update.message:
        await update.message.reply_text("📦 <b>Đã reset sạch toàn bộ dữ liệu.</b>", parse_mode="HTML")


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
        label = parse_label(text)
        number = None
        mnum = re.search(r"\b(\d{1,3})\b", normalize_text(text))
        if mnum:
            try:
                number = int(mnum.group(1))
            except ValueError:
                number = None

        pattern = parse_pattern(text)

        pattern_reply = None
        if pattern is not None:
            pattern_reply = brain.analyze_pattern(pattern)

        if label is not None:
            brain.add(label, number, pattern_key(pattern) if pattern else None)

            if pattern is not None:
                await update.message.reply_text(
                    "✅ <b>Đã lưu kết quả và phân tích mẫu.</b>\n"
                    f"{format_saved_message(label, number)}\n"
                    f"🧩 <b>Mẫu:</b> <code>{esc(pattern_key(pattern))}</code>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"<pre>{esc(pattern_reply or '')}</pre>",
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    format_saved_message(label, number),
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
            f"Gửi {LABEL_A} / {LABEL_B} hoặc nhập mẫu như 2-1, 3-1, 2-2...",
            parse_mode="HTML",
        )


# =========================
# MAIN
# =========================
def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("patterns", patterns_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("hardreset", reset_cmd))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle))

    print("Bot đang chạy...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
