import os
import ssl
import json
import time
import random
import threading
import requests
import paho.mqtt.client as mqtt

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext


# =========================
# ENV VARIABLES (Railway)
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


# =========================
# TELEGRAM SEND
# =========================

def send_telegram(text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": text
    }

    try:
        requests.post(url, data=data)
    except:
        pass


# =========================
# MQTT CONFIG
# =========================

BROKER = "www.wss8888.com"
PORT = 443
TOPIC = "#"

client_id = "client_" + str(random.randint(100000,999999))


# =========================
# MQTT EVENTS
# =========================

def on_connect(client, userdata, flags, rc):

    print("MQTT Connected:", rc)

    if rc == 0:

        client.subscribe(TOPIC)

        send_telegram("✅ MQTT CONNECTED")

    else:

        print("MQTT FAIL")


def on_message(client, userdata, msg):

    try:

        payload = msg.payload.decode("utf-8", errors="ignore")

        print("Topic:", msg.topic)
        print("Payload:", payload)

        try:

            data = json.loads(payload)

            send_telegram(f"📊 DATA\n{data}")

        except:

            send_telegram(f"📦 RAW\n{payload}")

    except Exception as e:

        print("Decode error:", e)


def on_disconnect(client, userdata, rc):

    print("Disconnected:", rc)

    time.sleep(5)

    try:
        client.reconnect()
    except:
        pass


# =========================
# START MQTT
# =========================

def start_mqtt():

    client = mqtt.Client(
        client_id=client_id,
        transport="websockets"
    )

    client.ws_set_options(
        path="/mqtt",
        headers={
            "Origin": "https://www.luckywin882.com",
            "User-Agent": "Mozilla/5.0"
        }
    )

    client.tls_set(cert_reqs=ssl.CERT_NONE)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    print("Connecting MQTT...")

    client.connect(BROKER, PORT, 30)

    client.loop_forever()


# =========================
# TELEGRAM BOT
# =========================

def start(update: Update, context: CallbackContext):

    update.message.reply_text("🤖 TOOL MB5 ONLINE")


def status(update: Update, context: CallbackContext):

    update.message.reply_text("✅ BOT RUNNING")


def help(update: Update, context: CallbackContext):

    update.message.reply_text("/start\n/status\n/help")


def start_telegram():

    updater = Updater(BOT_TOKEN)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("help", help))

    updater.start_polling()

    updater.idle()


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    mqtt_thread = threading.Thread(target=start_mqtt)

    mqtt_thread.start()

    start_telegram()
