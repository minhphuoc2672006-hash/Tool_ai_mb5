def analyze(history):
    if len(history) < 2:
        return {
            "predict": "KHÔNG RÕ",
            "confidence": 0.5,
            "reason": "Thiếu dữ liệu"
        }

    streak = 1
    last = history[-1] >= 11

    for x in reversed(history[:-1]):
        if (x >= 11) == last:
            streak += 1
        else:
            break

    trend = history[-1] - history[-2]

    if streak >= 4 and trend < 0:
        return {
            "predict": "XỈU",
            "confidence": 0.7,
            "reason": "Bệt Tài giảm → gãy"
        }

    if history[-1] <= 7:
        return {
            "predict": "XỈU",
            "confidence": 0.65,
            "reason": "Xỉu mạnh → đi tiếp"
        }

    return {
        "predict": "TÀI" if last else "XỈU",
        "confidence": 0.55,
        "reason": "Theo cầu"
    }
