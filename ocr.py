def split_money(total):
    return {
        "Lệnh 1": int(total * 0.25),
        "Lệnh 2": int(total * 0.2),
        "Lệnh 3": int(total * 0.15),
        "Lệnh 4": int(total * 0.1),
        "Gấp nhẹ": int(total * 0.1),
        "Dự phòng": int(total * 0.2),
    }
