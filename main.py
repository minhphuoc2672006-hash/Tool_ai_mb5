#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import pickle
from collections import defaultdict

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= ENV =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID") or "0")

if not TOKEN:
    raise Exception("Thiếu BOT_TOKEN")

bot = telebot.TeleBot(TOKEN)

# ================= FILES / LIMITS =================
DATA_FILE = "data.txt"
MODEL_FILE = "model.pkl"

MAX_HISTORY = 400
WINDOW_SIZES = [4, 5, 6, 7]     # bắt cụm ngắn + dài
MIN_CLUSTER_SIM = 0.75
MAX_CLUSTER_SAMPLES = 60

# ================= MEMORY =================
raw_numbers = []    # số gốc 3..18
tx_stream = []      # 1 = Tài, 0 = Xỉu, None = bão
valid_tx = []       # chỉ T/X
streaks = []        # độ dài các streak liên tiếp

state = {
    "markov": {},   # { (a,b,c): [x_count, t_count] }
    "clusters": {}  # { win_size: {cluster_id: {...}} }
}

# ================= BASIC UTILS =================
def is_admin(msg):
    if ADMIN_ID == 0:
        return True
    if not getattr(msg, "from_user", None):
        return False
    return msg.from_user.id == ADMIN_ID

def parse_input(text):
    if not text:
        return []
    nums = re.findall(r"-?\d+", text)
    out = []
    for n in nums:
        try:
            out.append(int(n))
        except ValueError:
            pass
    return out

def to_tx(num):
    if num in (3, 18):
        return None
    if 11 <= num <= 17:
        return 1
    if 4 <= num <= 10:
        return 0
    return None

def tx_name(v):
    if v == 1:
        return "TÀI"
    if v == 0:
        return "XỈU"
    return "BÃO"

# ================= HISTORY / STREAKS =================
def build_streaks(seq):
    out = []
    current = None
    count = 0

    for v in seq:
        if v is None:
            if count > 0:
                out.append(count)
            current = None
            count = 0
            continue

        if current is None:
            current = v
            count = 1
        elif v == current:
            count += 1
        else:
            out.append(count)
            current = v
            count = 1

    if count > 0:
        out.append(count)

    return out

# ================= CLUSTER ENGINE =================
def cluster_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0

    score = 0.0
    for x, y in zip(a, b):
        if x == y:
            score += 1.0
        elif abs(x - y) <= 1:
            score += 0.75
    return score / len(a)

def compute_prototype(samples):
    if not samples:
        return ()
    if len(samples) == 1:
        return tuple(samples[0])

    cols = list(zip(*samples))
    proto = []
    for col in cols:
        proto.append(int(round(sum(col) / len(col))))
    return tuple(proto)

def cluster_kind(proto):
    if not proto:
        return "CHƯA_RÕ"

    if len(proto) == 1:
        return "NGẮN"

    diffs = [proto[i + 1] - proto[i] for i in range(len(proto) - 1)]
    signs = [0 if d == 0 else (1 if d > 0 else -1) for d in diffs]

    if all(x == proto[0] for x in proto):
        return "BỆT_ĐỀU"

    if all(d > 0 for d in diffs):
        return "TĂNG_DẦN"

    if all(d < 0 for d in diffs):
        return "GIẢM_DẦN"

    if all(s != 0 for s in signs) and all(signs[i] != signs[i + 1] for i in range(len(signs) - 1)):
        return "ĐẢO/SHORT-LONG"

    if signs.count(0) >= 1:
        return "LỆCH_NHẸ"

    return "HỖN_HỢP"

def merge_sample_into_clusters(clusters, sample, seen_at):
    if not sample:
        return

    best_key = None
    best_score = 0.0

    for key, info in clusters.items():
        score = cluster_similarity(sample, info["prototype"])
        if score > best_score:
            best_score = score
            best_key = key

    if best_key is not None and best_score >= MIN_CLUSTER_SIM:
        info = clusters[best_key]
        info["count"] += 1
        info["last_seen"] = seen_at
        info["samples"].append(sample)
        if len(info["samples"]) > MAX_CLUSTER_SAMPLES:
            info["samples"] = info["samples"][-MAX_CLUSTER_SAMPLES:]
        info["prototype"] = compute_prototype(info["samples"])
        info["kind"] = cluster_kind(info["prototype"])
        return

    new_id = f"C{len(clusters) + 1:03d}"
    clusters[new_id] = {
        "prototype": tuple(sample),
        "samples": [tuple(sample)],
        "count": 1,
        "kind": cluster_kind(sample),
        "first_seen": seen_at,
        "last_seen": seen_at,
    }

def build_clusters_from_streaks(streak_list):
    clusters_by_window = {}

    for win in WINDOW_SIZES:
        clusters = {}
        if len(streak_list) >= win:
            for i in range(len(streak_list) - win + 1):
                sample = tuple(streak_list[i:i + win])
                merge_sample_into_clusters(clusters, sample, i)
        clusters_by_window[win] = clusters

    return clusters_by_window

# ================= PERSISTENCE =================
def save_data_append(nums):
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        for n in nums:
            f.write(f"{n}\n")

def save_state():
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(state, f)

def load_state():
    if not os.path.exists(MODEL_FILE):
        return {"markov": {}, "clusters": {}}
    try:
        with open(MODEL_FILE, "rb") as f:
            obj = pickle.load(f)
        if not isinstance(obj, dict):
            return {"markov": {}, "clusters": {}}
        return {
            "markov": obj.get("markov", {}),
            "clusters": obj.get("clusters", {}),
        }
    except:
        return {"markov": {}, "clusters": {}}

def load_history_from_file():
    nums = []
    if not os.path.exists(DATA_FILE):
        return nums
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            for line in f:
                for n in parse_input(line):
                    if 3 <= n <= 18:
                        nums.append(n)
    except:
        pass
    return nums

# ================= REBUILD =================
def rebuild_all():
    global tx_stream, valid_tx, streaks, state

    tx_stream = [to_tx(n) for n in raw_numbers]
    valid_tx = [v for v in tx_stream if v is not None]
    streaks = build_streaks(tx_stream)

    markov = {}
    if len(valid_tx) >= 4:
        for i in range(len(valid_tx) - 3):
            key = tuple(valid_tx[i:i + 3])
            nxt = valid_tx[i + 3]
            if key not in markov:
                markov[key] = [0, 0]  # [X, T]
            markov[key][nxt] += 1

    clusters = build_clusters_from_streaks(streaks)

    state = {
        "markov": markov,
        "clusters": clusters
    }

# ================= ANALYSIS =================
def get_current_cluster():
    if len(streaks) < min(WINDOW_SIZES):
        return None

    result = []
    for win in WINDOW_SIZES:
        if len(streaks) < win:
            continue

        sample = tuple(streaks[-win:])
        clusters = state.get("clusters", {}).get(win, {})
        best_key = None
        best_score = 0.0

        for key, info in clusters.items():
            score = cluster_similarity(sample, info["prototype"])
            if score > best_score:
                best_score = score
                best_key = key

        if best_key is not None:
            info = clusters[best_key]
            result.append({
                "window": win,
                "id": best_key,
                "sample": sample,
                "prototype": info["prototype"],
                "kind": info["kind"],
                "score": best_score,
                "count": info["count"],
            })
        else:
            result.append({
                "window": win,
                "id": "NEW",
                "sample": sample,
                "prototype": sample,
                "kind": cluster_kind(sample),
                "score": 0.0,
                "count": 0,
            })

    if not result:
        return None

    return max(result, key=lambda x: (x["score"], x["window"]))

def predict_markov():
    if len(valid_tx) < 3:
        return None, 0.0

    key = tuple(valid_tx[-3:])
    counts = state.get("markov", {}).get(key)
    if not counts:
        return None, 0.0

    x_count, t_count = counts[0], counts[1]
    total = x_count + t_count
    if total < 3:
        return None, 0.0

    p_t = t_count / total
    p_x = x_count / total

    if abs(p_t - p_x) < 0.08:
        return None, 0.5

    return (1, p_t) if p_t > p_x else (0, p_x)

def decide_result():
    if not valid_tx:
        return "Không rõ", 0.5

    last = valid_tx[-1]
    cluster = get_current_cluster()
    ai_pred, ai_conf = predict_markov()

    score_t = 0.0
    score_x = 0.0

    if cluster:
        kind = cluster["kind"]
        sim = cluster["score"]
        weight = 1.0 if sim >= 0.85 else 0.7 if sim >= 0.75 else 0.4

        if kind == "BỆT_ĐỀU":
            if last == 1:
                score_t += 1.2 * weight
            else:
                score_x += 1.2 * weight

        elif kind == "ĐẢO/SHORT-LONG":
            if last == 1:
                score_x += 1.2 * weight
            else:
                score_t += 1.2 * weight

        else:
            score_t += 0.15 * weight
            score_x += 0.15 * weight

    if ai_pred is not None:
        if ai_pred == 1:
            score_t += 1.6 * ai_conf
        else:
            score_x += 1.6 * ai_conf

    if len(valid_tx) >= 10:
        bias = sum(valid_tx) / len(valid_tx)
        if bias > 0.65:
            score_x += 0.4
        elif bias < 0.35:
            score_t += 0.4

    total = score_t + score_x
    if total <= 0:
        return "Không rõ", 0.5

    p_t = score_t / total
    if abs(p_t - 0.5) < 0.05:
        return "Không rõ", 0.5

    return ("TÀI", p_t) if p_t > 0.5 else ("XỈU", 1 - p_t)

def clusters_summary(max_items=10):
    lines = []
    clusters_by_window = state.get("clusters", {})
    for win in WINDOW_SIZES:
        clusters = clusters_by_window.get(win, {})
        if not clusters:
            lines.append(f"• Window {win}: chưa có cụm")
            continue

        top = sorted(clusters.items(), key=lambda kv: kv[1]["count"], reverse=True)[:max_items]
        lines.append(f"• Window {win}: {len(clusters)} cụm")
        for cid, info in top:
            proto = "-".join(map(str, info["prototype"]))
            lines.append(f"  - {cid} | {info['kind']} | n={info['count']} | {proto}")
    return "\n".join(lines)

# ================= UI =================
def main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Nhập dữ liệu", callback_data="menu_input"),
        InlineKeyboardButton("📊 Thống kê", callback_data="menu_stats"),
        InlineKeyboardButton("🧩 Cụm", callback_data="menu_clusters"),
        InlineKeyboardButton("🔄 Train", callback_data="menu_train"),
        InlineKeyboardButton("🧹 Reset", callback_data="menu_reset"),
        InlineKeyboardButton("ℹ️ Hướng dẫn", callback_data="menu_help"),
    )
    return kb

def confirm_reset_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Xác nhận reset", callback_data="reset_yes"),
        InlineKeyboardButton("❌ Hủy", callback_data="reset_no"),
    )
    return kb

def format_dashboard():
    cluster = get_current_cluster()
    result, conf = decide_result()
    ai_pred, ai_conf = predict_markov()

    ai_text = "??"
    if ai_pred == 1:
        ai_text = "TÀI"
    elif ai_pred == 0:
        ai_text = "XỈU"

    cluster_text = "Chưa đủ dữ liệu để nhận cụm."
    if cluster:
        cluster_text = (
            f"Window: {cluster['window']}\n"
            f"Mã cụm: {cluster['id']}\n"
            f"Loại: {cluster['kind']}\n"
            f"Mẫu hiện tại: {cluster['sample']}\n"
            f"Đại diện: {cluster['prototype']}\n"
            f"Khớp: {round(cluster['score'] * 100)}%\n"
            f"Số lần gặp: {cluster['count']}"
        )

    last_num = raw_numbers[-1] if raw_numbers else None
    last_tx = tx_name(tx_stream[-1]) if tx_stream else "N/A"

    return (
        f"🤖 <b>AI Pattern Tool</b>\n\n"
        f"📌 Số cuối: <b>{last_num if last_num is not None else 'N/A'}</b> ({last_tx})\n\n"
        f"🧩 <b>Cụm hiện tại</b>\n{cluster_text}\n\n"
        f"🧠 <b>Gợi ý tham khảo</b>: <b>{result}</b>\n"
        f"📈 Tin cậy: <b>{round(conf * 100)}%</b>\n"
        f"🔎 AI Markov: <b>{ai_text}</b> ({round(ai_conf * 100)}%)\n\n"
        f"📚 Tổng số phiên: <b>{len(raw_numbers)}</b>\n"
        f"🎯 Số T/X hợp lệ: <b>{len(valid_tx)}</b>\n"
        f"🧱 Streak hiện tại: <b>{streaks[-min(len(streaks), max(WINDOW_SIZES)):] if streaks else []}</b>"
    )

# ================= COMMANDS =================
@bot.message_handler(commands=["start"])
def start(msg):
    if not is_admin(msg):
        return
    bot.send_message(
        msg.chat.id,
        "BOT AI PRO đã sẵn sàng.\nNhập chuỗi số như: 11-10-13-8-12-6\nBot sẽ tự lưu, tự chia cụm ngắn/dài, và hiển thị giao diện nút bấm.",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=["menu"])
def menu(msg):
    if not is_admin(msg):
        return
    bot.send_message(msg.chat.id, "Chọn chức năng bên dưới:", reply_markup=main_menu())

@bot.message_handler(commands=["help"])
def help_cmd(msg):
    if not is_admin(msg):
        return
    bot.send_message(
        msg.chat.id,
        "Cách dùng:\n"
        "• Nhập dữ liệu thật: 11-10-13-8-12\n"
        "• /stats xem thống kê\n"
        "• /clusters xem các cụm\n"
        "• /train rebuild model\n"
        "• /reset xóa toàn bộ dữ liệu\n\n"
        "Lưu ý: số 3 và 18 được xem là bão, bot vẫn nhận nhưng sẽ tách khỏi T/X.",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=["stats"])
def stats(msg):
    if not is_admin(msg):
        return
    cluster_count = sum(len(v) for v in state.get("clusters", {}).values())
    bot.send_message(
        msg.chat.id,
        f"📊 <b>Thống kê</b>\n\n"
        f"• Tổng số đã nhập: <b>{len(raw_numbers)}</b>\n"
        f"• T/X hợp lệ: <b>{len(valid_tx)}</b>\n"
        f"• Số cụm đang giữ: <b>{cluster_count}</b>\n"
        f"• Window cụm: <b>{WINDOW_SIZES}</b>\n"
        f"• Streak hiện tại: <b>{streaks[-10:] if streaks else []}</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@bot.message_handler(commands=["clusters"])
def clusters_cmd(msg):
    if not is_admin(msg):
        return
    text = clusters_summary(max_items=6)
    bot.send_message(
        msg.chat.id,
        f"🧩 <b>Danh sách cụm</b>\n\n{text}",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@bot.message_handler(commands=["train"])
def train_cmd(msg):
    if not is_admin(msg):
        return
    rebuild_all()
    save_state()
    bot.send_message(
        msg.chat.id,
        f"✅ Train xong.\n"
        f"• Tổng phiên: {len(raw_numbers)}\n"
        f"• Số cụm: {sum(len(v) for v in state.get('clusters', {}).values())}",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=["reset"])
def reset_cmd(msg):
    if not is_admin(msg):
        return
    bot.send_message(msg.chat.id, "Bạn có chắc muốn xóa toàn bộ dữ liệu?", reply_markup=confirm_reset_menu())

# ================= CALLBACKS =================
@bot.callback_query_handler(func=lambda call: True)
def on_callback(call):
    if not is_admin(call.message):
        bot.answer_callback_query(call.id, "Không có quyền")
        return

    data = call.data

    try:
        if data == "menu_input":
            bot.edit_message_text(
                "➕ Nhập kết quả thật vào chat theo dạng:\n"
                "11-10-13-8-12-6\n\n"
                "Bot sẽ tự học cụm ngắn và dài.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu()
            )

        elif data == "menu_stats":
            cluster_count = sum(len(v) for v in state.get("clusters", {}).values())
            bot.edit_message_text(
                f"📊 <b>Thống kê</b>\n\n"
                f"• Tổng số đã nhập: <b>{len(raw_numbers)}</b>\n"
                f"• T/X hợp lệ: <b>{len(valid_tx)}</b>\n"
                f"• Số cụm đang giữ: <b>{cluster_count}</b>\n"
                f"• Window cụm: <b>{WINDOW_SIZES}</b>\n"
                f"• Streak hiện tại: <b>{streaks[-10:] if streaks else []}</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu(),
                parse_mode="HTML"
            )

        elif data == "menu_clusters":
            text = clusters_summary(max_items=6)
            bot.edit_message_text(
                f"🧩 <b>Danh sách cụm</b>\n\n{text}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu(),
                parse_mode="HTML"
            )

        elif data == "menu_train":
            rebuild_all()
            save_state()
            bot.answer_callback_query(call.id, "Train xong")
            bot.edit_message_text(
                f"✅ Train xong.\n"
                f"• Tổng phiên: {len(raw_numbers)}\n"
                f"• Số cụm: {sum(len(v) for v in state.get('clusters', {}).values())}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu()
            )

        elif data == "menu_reset":
            bot.edit_message_text(
                "Bạn có chắc muốn xóa toàn bộ dữ liệu?",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=confirm_reset_menu()
            )

        elif data == "reset_yes":
            raw_numbers.clear()
            tx_stream.clear()
            valid_tx.clear()
            streaks.clear()
            state["markov"] = {}
            state["clusters"] = {}

            try:
                if os.path.exists(DATA_FILE):
                    os.remove(DATA_FILE)
            except:
                pass

            try:
                if os.path.exists(MODEL_FILE):
                    os.remove(MODEL_FILE)
            except:
                pass

            bot.edit_message_text(
                "🧹 Đã reset toàn bộ dữ liệu.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu()
            )

        elif data == "reset_no":
            bot.edit_message_text(
                "Đã hủy reset.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu()
            )

        elif data == "menu_help":
            bot.edit_message_text(
                "Cách dùng:\n"
                "• Nhập dữ liệu thật: 11-10-13-8-12\n"
                "• /stats xem thống kê\n"
                "• /clusters xem các cụm\n"
                "• /train rebuild model\n"
                "• /reset xóa toàn bộ dữ liệu\n\n"
                "Số 3 và 18 sẽ được tách riêng như bão.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=main_menu()
            )

        bot.answer_callback_query(call.id)

    except Exception:
        bot.answer_callback_query(call.id, "Đã có lỗi nhỏ, thử lại.")
        return

# ================= INPUT HANDLER =================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(msg):
    if not is_admin(msg):
        return

    text = msg.text or ""
    if text.startswith("/"):
        return

    nums = parse_input(text)
    valid_nums = [n for n in nums if 3 <= n <= 18]

    if not valid_nums:
        bot.reply_to(msg, "Chỉ nhận số từ 3 đến 18. Ví dụ: 11-10-13-8")
        return

    raw_numbers.extend(valid_nums)
    if len(raw_numbers) > MAX_HISTORY:
        raw_numbers[:] = raw_numbers[-MAX_HISTORY:]

    save_data_append(valid_nums)
    rebuild_all()
    save_state()

    cluster = get_current_cluster()
    result, conf = decide_result()
    ai_pred, ai_conf = predict_markov()

    ai_text = "??"
    if ai_pred == 1:
        ai_text = "TÀI"
    elif ai_pred == 0:
        ai_text = "XỈU"

    if cluster:
        cluster_text = (
            f"Window: {cluster['window']}\n"
            f"Mã cụm: {cluster['id']}\n"
            f"Loại: {cluster['kind']}\n"
            f"Mẫu hiện tại: {cluster['sample']}\n"
            f"Đại diện: {cluster['prototype']}\n"
            f"Khớp: {round(cluster['score'] * 100)}%\n"
            f"Số lần gặp: {cluster['count']}"
        )
    else:
        cluster_text = "Chưa đủ dữ liệu để nhận cụm."

    last_num = valid_nums[-1]
    last_tx = tx_name(to_tx(last_num))

    bot.send_message(
        msg.chat.id,
        f"✅ Đã nhận: <b>{last_num}</b> ({last_tx})\n\n"
        f"🧩 <b>Cụm hiện tại</b>\n{cluster_text}\n\n"
        f"🧠 <b>Gợi ý tham khảo</b>: <b>{result}</b>\n"
        f"📈 Tin cậy: <b>{round(conf * 100)}%</b>\n"
        f"🔎 AI Markov: <b>{ai_text}</b> ({round(ai_conf * 100)}%)\n\n"
        f"📚 Tổng phiên: <b>{len(raw_numbers)}</b>\n"
        f"🎯 T/X hợp lệ: <b>{len(valid_tx)}</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

# ================= BOOTSTRAP =================
def bootstrap():
    global raw_numbers
    raw_numbers = load_history_from_file()
    rebuild_all()

    saved = load_state()
    if isinstance(saved, dict):
        if saved.get("markov"):
            state["markov"] = saved["markov"]
        if saved.get("clusters"):
            state["clusters"] = saved["clusters"]

bootstrap()

# ================= RUN =================
bot.infinity_polling(skip_pending=True)
