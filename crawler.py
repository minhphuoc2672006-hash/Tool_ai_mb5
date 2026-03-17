import websocket
import json
from bot import set_result

WS_URL = "wss://www.wss8888.com/mqtt"

# 🔓 decode data
def decode_data(message):
    try:
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except:
                print("HEX:", message.hex())
                return

        if "HD_push" in message:
            print("🎯 RAW:", message)

            try:
                data = json.loads(message)

                # ⚠️ tùy server → chỉnh key nếu cần
                if "result" in data:
                    dice = data["result"]  # ví dụ [2,5,6]
                    total = sum(dice)

                    if total >= 11:
                        kq = "TÀI"
                    else:
                        kq = "XỈU"

                    result_text = f"{dice} → {kq}"
                    print("✅ RESULT:", result_text)

                    set_result(result_text)

                else:
                    set_result(message)

            except Exception as e:
                print("JSON error:", e)

    except Exception as e:
        print("Decode error:", e)


def on_message(ws, message):
    decode_data(message)


def on_error(ws, error):
    print("❌ WS Error:", error)


def on_close(ws, close_status_code, close_msg):
    print("⚠️ WS Closed → reconnecting...")


def on_open(ws):
    print("✅ Connected WebSocket")

    client_id = "tool_ai_mb5"

    # MQTT CONNECT
    payload = (
        b"\x10" +
        bytes([12 + len(client_id)]) +
        b"\x00\x04MQTT" +
        b"\x04" +
        b"\x02" +
        b"\x00\x3c" +
        bytes([0, len(client_id)]) +
        client_id.encode()
    )

    ws.send(payload)

    # 🔥 SUBSCRIBE topic thật
    topic = "bigSmallMD5/HD_push"

    subscribe = (
        b"\x82" +
        bytes([5 + len(topic)]) +
        b"\x00\x01" +
        bytes([0, len(topic)]) +
        topic.encode() +
        b"\x00"
    )

    ws.send(subscribe)

    print("📡 Subscribed:", topic)


def start_crawler():
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                subprotocols=["mqttv3.1"]
            )

            ws.run_forever()

        except Exception as e:
            print("🔁 Reconnect error:", e)
