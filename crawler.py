import paho.mqtt.client as mqtt
import ssl
import json
import time

BROKER = "www.wss8888.com"
PORT = 443
TOPIC = "#"

# ===== MQTT CONNECT =====

def on_connect(client, userdata, flags, rc):
    print("MQTT Connected:", rc)

    if rc == 0:
        client.subscribe(TOPIC)
        print("Subscribed:", TOPIC)
    else:
        print("Connect failed")


# ===== RECEIVE DATA =====

def on_message(client, userdata, msg):

    try:
        data = msg.payload.decode("utf-8", errors="ignore")

        print("Topic:", msg.topic)
        print("Payload:", data)

        # nếu là json
        try:
            j = json.loads(data)
            print("JSON:", j)

        except:
            pass

    except Exception as e:
        print("Decode error:", e)


# ===== ERROR =====

def on_disconnect(client, userdata, rc):
    print("Disconnected:", rc)

    time.sleep(5)

    try:
        client.reconnect()
    except:
        pass


# ===== CREATE CLIENT =====

client = mqtt.Client(
    transport="websockets",
    protocol=mqtt.MQTTv311
)

# headers giống browser

client.ws_set_options(
    path="/mqtt",
    headers={
        "Origin": "https://www.luckywin882.com",
        "User-Agent": "Mozilla/5.0",
    }
)

# TLS

client.tls_set(cert_reqs=ssl.CERT_NONE)

client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect


# ===== CONNECT =====

print("Connecting MQTT...")

client.connect(BROKER, PORT, 60)

client.loop_forever()
