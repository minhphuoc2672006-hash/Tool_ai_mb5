import asyncio
import websockets
import json
import time

from storage import add
from ai import predict
from bot import send

WS_URL = "wss://www.wss8888.com/mqtt"

last_round = None


def get_result(total):

    if total >= 11:
        return "TAI"
    else:
        return "XIU"


async def run():

    global last_round

    while True:

        try:

            print("Connecting WebSocket...")

            async with websockets.connect(WS_URL) as ws:

                print("Connected")

                while True:

                    msg = await ws.recv()

                    try:

                        data = json.loads(msg)

                        # realtime push
                        if "HD_push" in msg:

                            dice = data["dice"]

                            d1 = dice[0]
                            d2 = dice[1]
                            d3 = dice[2]

                            total = d1 + d2 + d3

                            result = get_result(total)

                            round_id = data["round"]

                            if round_id != last_round:

                                last_round = round_id

                                add(result)

                                guess = predict()

                                text = f"""
🎲 TÀI XỈU RESULT

Round: {round_id}

Dice: {d1}-{d2}-{d3}

Total: {total}
Result: {result}

AI Predict: {guess}
"""

                                send(text)

                    except:
                        pass

        except Exception as e:

            print("WS error:", e)

            print("Reconnect in 5s")

            time.sleep(5)

asyncio.run(run())
