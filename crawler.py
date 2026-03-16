import websocket
import time
import ssl

WS_URL = "wss://www.wss8888.com/mqtt"

def on_open(ws):
    print("Connected to WebSocket")

def on_message(ws, message):
    print("DATA:", message)

def on_error(ws, error):
    print("ERROR:", error)

def on_close(ws, close_status_code, close_msg):
    print("Closed connection")

while True:

    try:

        ws = websocket.WebSocketApp(
            WS_URL,
            subprotocols=["mqtt"],
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        ws.run_forever(
            sslopt={"cert_reqs": ssl.CERT_NONE}
        )

    except Exception as e:

        print("Reconnect after 5s", e)
        time.sleep(5)
