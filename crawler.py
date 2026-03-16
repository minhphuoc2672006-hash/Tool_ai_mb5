import paho.mqtt.client as mqtt
import ssl
import random
import json
import time

BROKER = "www.wss8888.com"
PORT = 443
TOPIC = "#"

client_id = "client_" + str(random.randint(100000,999999))


def on_connect(client, userdata, flags, rc, properties=None):

    print("MQTT Connected:", rc)

    if rc == 0:

        client.subscribe(TOPIC)
        print("Subscribed:", TOPIC)


def on_message(client, userdata, msg):

    try:

        payload = msg.payload.decode("utf-8", errors="ignore")

        print("Topic:", msg.topic)
        print("Payload:", payload)

        try:

            data = json.loads(payload)
            print("JSON:", data)

        except:
            pass

    except Exception as e:

        print("Decode error:", e)


def on_disconnect(client, userdata, rc, properties=None):

    print("Disconnected:", rc)

    time.sleep(5)

    try:
        client.reconnect()
    except:
        pass


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

client.username_pw_set("guest", "guest")

client.tls_set(cert_reqs=ssl.CERT_NONE)

client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect


print("Connecting MQTT...")

client.connect(BROKER, PORT, keepalive=30)

client.loop_forever()
