def analyze(history):
    if len(history) < 5:
        return {
            "predict": "KHÔNG RÕ",
            "confidence": 0.5,
            "reason": "Thiếu dữ liệu"
        }

    tx = [1 if x >= 11 else 0 for x in history]

    streak = 1
    for i in range(len(tx)-2, -1, -1):
        if tx[i] == tx[-1]:
            streak += 1
        else:
            break

    trend = history[-1] - history[-2]

    last10 = tx[-10:]
    tai_count = sum(last10)
    xiu_count = len(last10) - tai_count

    pattern = "".join(map(str, tx[-6:]))

    if streak >= 5:
        return {
            "predict": "XỈU" if tx[-1] == 1 else "TÀI",
            "confidence": 0.75,
            "reason": f"Bệt {streak} → dễ gãy"
        }

    if pattern in ["1010", "0101", "10101", "01010"]:
        return {
            "predict": "TÀI" if tx[-1] == 0 else "XỈU",
            "confidence": 0.7,
            "reason": "Cầu đảo"
        }

    if tai_count >= 7:
        return {
            "predict": "XỈU",
            "confidence": 0.68,
            "reason": "Tài nhiều → hồi"
        }

    if xiu_count >= 7:
        return {
            "predict": "TÀI",
            "confidence": 0.68,
            "reason": "Xỉu nhiều → hồi"
        }

    if trend > 2:
        return {
            "predict": "TÀI",
            "confidence": 0.6,
            "reason": "Xu hướng tăng"
        }

    if trend < -2:
        return {
            "predict": "XỈU",
            "confidence": 0.6,
            "reason": "Xu hướng giảm"
        }

    return {
        "predict": "TÀI" if tx[-1] else "XỈU",
        "confidence": 0.55,
        "reason": "Theo cầu"
    }
