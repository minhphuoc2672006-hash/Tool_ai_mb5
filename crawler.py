import paho.mqtt.client as mqtt
import ssl
import random
import json
import time
import requests

# ===== TELEGRAM =====

BOT_TOKEN = "PUT_YOUR_BOT_TOKEN"
CHAT_ID = "PUT_YOUR_CHAT_ID"

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass


# ===== MQTT CONFIG =====

BROKER = "www.wss8888.com"
PORT = 443
TOPIC = "#"

client_id = "client_" + str(random.randint(100000,999999))


# ===== MQTT EVENTS =====

def on_connect(client, userdata, flags, rc, properties=None):

    print("MQTT Connected:", rc)

    if rc == 0:

        client.subscribe(TOPIC)

        print("Subscribed:", TOPIC)

        send_telegram("✅ MQTT Connected")

    else:

        print("Connect failed:", rc)


def on_message(client, userdata, msg):

    try:

        payload = msg.payload.decode("utf-8", errors="ignore")

        print("Topic:", msg.topic)
        print("Payload:", payload)

        # thử parse json
        try:

            data = json.loads(payload)

            print("JSON:", data)

            send_telegram(f"📊 DATA\n{data}")

        except:

            send_telegram(f"📦 RAW\n{payload}")

    except Exception as e:

        print("Decode error:", e)


def on_disconnect(client, userdata, rc, properties=None):

    print("Disconnected:", rc)

    send_telegram("⚠️ MQTT Disconnected")

    time.sleep(5)

    try:
        client.reconnect()
    except:
        pass


# ===== CREATE CLIENT =====

client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id=client_id,
    transport="websockets",
    protocol=mqtt.MQTTv311
)

client.ws_set_options(
    path="/mqtt",
    headers={
        "Origin": "https://www.luckywin882.com",
        "User-Agent": "Mozilla/5.0"
    }
)

client.username_pw_set("guest","guest")

client.tls_set(cert_reqs=ssl.CERT_NONE)

client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect


# ===== START =====

print("Connecting MQTT...")

client.connect(BROKER, PORT, keepalive=30)

client.loop_forever()
