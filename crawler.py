import websocket
import json
import time
import ssl

from storage import add
from ai import predict
from bot import send

WS_URL = "wss://www.wss8888.com/mqtt"


def on_message(ws, message):
    try:
        data = json.loads(message)

        if "dice" in data:

            d1, d2, d3 = data["dice"]
            total = d1 + d2 + d3

            result = "TAI" if total >= 11 else "XIU"

            add(result)

            ai_predict = predict()

            text = f"""
🎲 MB5 RESULT

Dice: {d1}-{d2}-{d3}
Total: {total}
Result: {result}

AI Predict: {ai_predict}
"""

            send(text)

    except Exception as e:
        print("PARSE ERROR:", e)


def on_error(ws, error):
    print("WS ERROR:", error)


def on_close(ws, close_status_code, close_msg):
    print("WS CLOSED")


def on_open(ws):
    print("Connected to WS")


while True:

    try:

        ws = websocket.WebSocketApp(
            WS_URL,
            subprotocols=["mqtt"],   # sửa lỗi ở đây
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        ws.on_open = on_open

        ws.run_forever(
            sslopt={"cert_reqs": ssl.CERT_NONE}
        )

    except Exception as e:

        print("Reconnect after 5s", e)
        time.sleep(5)
