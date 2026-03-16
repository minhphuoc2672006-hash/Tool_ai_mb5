from storage import get


def streak_predict(data):

    if len(data) < 4:
        return None

    last = data[-1]

    streak = 1

    for i in range(len(data)-2, -1, -1):

        if data[i] == last:
            streak += 1
        else:
            break

    if streak >= 3:
        return last

    return None


def opposite_predict(data):

    if len(data) < 6:
        return None

    last5 = data[-5:]

    if last5.count("TAI") == 5:
        return "XIU"

    if last5.count("XIU") == 5:
        return "TAI"

    return None


def ratio_predict(data):

    if len(data) < 15:
        return None

    last = data[-15:]

    tai = last.count("TAI")
    xiu = last.count("XIU")

    if tai > xiu:
        return "XIU"

    if xiu > tai:
        return "TAI"

    return None


def zigzag_predict(data):

    if len(data) < 6:
        return None

    last6 = data[-6:]

    pattern = ["TAI","XIU","TAI","XIU","TAI","XIU"]
    pattern2 = ["XIU","TAI","XIU","TAI","XIU","TAI"]

    if last6 == pattern:
        return "TAI"

    if last6 == pattern2:
        return "XIU"

    return None


def predict():

    data = get()

    if len(data) < 10:
        return "WAIT"

    p = streak_predict(data)
    if p:
        return p

    p = opposite_predict(data)
    if p:
        return p

    p = zigzag_predict(data)
    if p:
        return p

    p = ratio_predict(data)
    if p:
        return p

    return "50/50"
