from storage import get

def predict():

    data = get()

    if len(data) < 20:
        return "WAIT"

    last = data[-15:]

    tai = last.count("TAI")
    xiu = last.count("XIU")

    if tai > xiu:
        return "TAI"

    if xiu > tai:
        return "XIU"

    return "50/50"
