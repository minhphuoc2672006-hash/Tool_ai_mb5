history = []

def add(result):

    history.append(result)

    if len(history) > 5000:
        history.pop(0)

def get():
    return history
