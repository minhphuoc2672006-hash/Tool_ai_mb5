import ssl
import random
import paho.mqtt.client as mqtt

BROKER = "www.wss8888.com"
PORT = 443
TOPIC = "#"

client_id = "client_" + str(random.randint(100000,999999))


def on_connect(client, userdata, flags, rc):

    print("MQTT Connected:", rc)

    client.subscribe(TOPIC)

    print("Subscribed:", TOPIC)


def on_message(client, userdata, msg):

    try:
        payload = msg.payload.decode("utf-8", errors="ignore")

        print("Topic:", msg.topic)
        print("Payload:", payload)

    except Exception as e:

        print("Decode error:", e)


def start_crawler():

    client = mqtt.Client(client_id=client_id, transport="websockets")

    client.ws_set_options(path="/mqtt")

    client.tls_set(cert_reqs=ssl.CERT_NONE)

    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting MQTT...")

    client.connect(BROKER, PORT, 30)

    # QUAN TRỌNG (không dùng loop_forever)
    client.loop_start()
