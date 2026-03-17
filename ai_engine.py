def analyze(history):
    tai = sum(1 for x in history if x >= 11)
    xiu = len(history) - tai

    streak = 0
    last = history[-1] >= 11

    for x in reversed(history):
        if (x >= 11) == last:
            streak += 1
        else:
            break

    trend = "decrease" if history[-1] < history[-2] else "increase"

    # logic giống mình phân tích cho bạn
    if streak >= 4 and trend == "decrease":
        return {
            "predict": "XỈU",
            "confidence": 0.7,
            "reason": "Bệt tài yếu dần → sắp gãy"
        }

    if streak >= 2:
        return {
            "predict": "TÀI",
            "confidence": 0.6,
            "reason": "Đang bệt tài"
        }

    return {
        "predict": "XỈU",
        "confidence": 0.5,
        "reason": "Ngẫu nhiên"
    }
