import asyncio
import websockets
import json
import time

from storage import add
from ai import predict
from bot import send

WS_URL = "wss://www.wss8888.com/mqtt"

last_round = None


def result_from_total(total):

    if total >= 11:
        return "TAI"
    else:
        return "XIU"


async def run():

    global last_round

    while True:

        try:

            print("Connecting WS...")

            async with websockets.connect(WS_URL) as ws:

                print("Connected")

                while True:

                    msg = await ws.recv()

                    try:

                        data = json.loads(msg)

                        if "dice" in data:

                            d1 = data["dice"][0]
                            d2 = data["dice"][1]
                            d3 = data["dice"][2]

                            total = d1 + d2 + d3

                            result = result_from_total(total)

                            round_id = data.get("round", "unknown")

                            if round_id != last_round:

                                last_round = round_id

                                add(result)

                                guess = predict()

                                text = f"""
🎲 MB5 RESULT

Round: {round_id}

Dice: {d1}-{d2}-{d3}

Total: {total}
Result: {result}

AI Predict: {guess}
"""

                                print(text)

                                send(text)

                    except:
                        pass

        except Exception as e:

            print("WS ERROR:", e)

            print("Reconnect after 5s")

            time.sleep(5)

asyncio.run(run())
