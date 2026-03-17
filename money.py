def split_money(total):
    return {
        "Lệnh 1 (chính)": int(total * 0.3),
        "Lệnh 2": int(total * 0.2),
        "Lệnh 3": int(total * 0.2),
        "Lệnh 4": int(total * 0.1),
        "Dự phòng": int(total * 0.2),
    }
