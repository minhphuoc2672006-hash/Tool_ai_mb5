import pickle

data = []

# đọc data
with open("data.txt") as f:
    for line in f:
        n = int(line.strip())
        tx = 1 if n >= 11 else 0
        data.append(tx)

# tạo model
model = {}

for i in range(len(data)-3):
    key = tuple(data[i:i+3])
    nxt = data[i+3]

    if key not in model:
        model[key] = [0, 0]

    model[key][nxt] += 1

# lưu model
with open("model.pkl", "wb") as f:
    pickle.dump(model, f)

print("Train xong!")
