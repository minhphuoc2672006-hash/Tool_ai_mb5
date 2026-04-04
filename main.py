import os
import re
import json
import math
import sqlite3
import asyncio
import logging
import time
import base64
from io import BytesIO
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from telegram import Update
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "ai_state.db")

THRESHOLD = int(os.getenv("THRESHOLD", "11"))
LOW_LABEL = os.getenv("LOW_LABEL", "Xỉu")
HIGH_LABEL = os.getenv("HIGH_LABEL", "Tài")

RECENT_CACHE = int(os.getenv("RECENT_CACHE", "500"))
MAX_KEEP_HISTORY = int(os.getenv("MAX_KEEP_HISTORY", "0"))
MAX_INPUT_NUMS = int(os.getenv("MAX_INPUT_NUMS", "120"))
USER_CACHE_LIMIT = int(os.getenv("USER_CACHE_LIMIT", "500"))
MIN_ANALYSIS_LEN = int(os.getenv("MIN_ANALYSIS_LEN", "6"))
HISTORY_ANALYSIS_LIMIT = int(os.getenv("HISTORY_ANALYSIS_LIMIT", "0"))

MIN_PREDICTION_DATA = int(os.getenv("MIN_PREDICTION_DATA", "20"))
CLEAR_PATTERN_MIN_SCORE = int(os.getenv("CLEAR_PATTERN_MIN_SCORE", "80"))
LOSS_STREAK_LIMIT = int(os.getenv("LOSS_STREAK_LIMIT", "5"))

# Chờ thêm 1 nhịp để xác nhận cầu mới
CONFIRM_NEW_PATTERN_MIN_SCORE = int(os.getenv("CONFIRM_NEW_PATTERN_MIN_SCORE", "88"))

# Robot hiển thị chờ phân tích
ROBOT_ANALYZE_DELAY = float(os.getenv("ROBOT_ANALYZE_DELAY", "5"))
ROBOT_IMAGE_PATH = os.getenv("ROBOT_IMAGE_PATH", "robot.jpg")

# Ảnh robot được nhúng sẵn để code tự tạo file khi chạy
ROBOT_IMAGE_B64 = """/9j/4AAQSkZJRgABAQAASABIAAD/4QCMRXhpZgAATU0AKgAAAAgABQESAAMAAAABAAEAAAEaAAUAAAABAAAASgEbAAUAAAABAAAAUgEoAAMAAAABAAIAAIdpAAQAAAABAAAAWgAAAAAAAABIAAAAAQAAAEgAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAAAWigAwAEAAAAAQAAAWgAAAAA/8AAEQgBaAFoAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAgICAgICAwICAwUDAwMFBgUFBQUGCAYGBgYGCAoICAgICAgKCgoKCgoKCgwMDAwMDA4ODg4ODw8PDw8PDw8PD//bAEMBAgMDBAQEBwQEBxALCQsQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEP/dAAQAF//aAAwDAQACEQMRAD8A/biiiigAr0SvO69EoAKKKKAPO6KKKACvRK87r0SgAooooA87ooooAK9ErzuvRKACiiigDzuiiigAr0SvO69EoAKKKKAPO6KKKACvRK87r0SgAooooA87ooooAK9ErzuvRKACiiigDzuiiigAr0SvO69EoAKKKKAPO6KKKACiiigD/9D9uKK9EooA83r0iivN6APSKK87qOgAqSvRKKAPN69IorzegD0iivO6joAKkr0SigDzevSKK83oA9Iorzuo6ACpK9EooA83r0iivN6APSKK87qOgAqSvRKKAPN69IorzegD0iivO6joAKkr0SigDzevSKK83oA9Iorzuo6ACpK9EooA83r0iivN6APSKK87qOgAqSvRKKAPO6K9EooA/9H9/KKKKACvO69ErzegCSiio6APSKKKKACvO69ErzegCSiio6APSKKKKACvO69ErzegCSiij/vmgD0SisB9WWdvLsgWI9uT9Knto2uk3u5I96ALn223/v1wX+q/vSV30gt4BkoPyzWPc620I/dRB/8AgVAHES6t5XPkNWfN4mtQ3lSwSf8AASrf1rqL/wAT3ixyW4hiLFW7nFeV3dAHqkfxM8Lv/rpJYP8ArpEVrp9O8Q6JqqhtOvobgf7LjP5V8vXdcbdxe9AH3dXndfOGi/FTxh4ZZVln/tGzXjyrksXx2xJya9p8M+LNG8V2ol0xyJ1UF7d/vpmgDpqKKjoA9IooooAK87r0SvN6AJKKKjoA9IooooAK87r0SvN6AJKKKjoA9IooooAKKKKAP//S/biiiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigCOvSK87rpL3WUtr6LTUHmXEnJHonrQBu+YPSvMNQ8RjV7m4itRmzsp3tmb1libEg/4DXfgASebJ9+vnrSRLpHiHxF4Yuj/pFnfTX0ODx9j1GR5sD6HfuoA968PSwy6eDEQSGO7Hr71I90n2hxBye9edQ3dav2ugDqPN9q527qH7XWVNd0AVLuuTu61ruaudu6AMW7rk7utu7mrmLugDn7usfTde1PwtrFtrujtuuLY8g/xjvGf9k1cu65PUJvKhkml/dxxqzNQB+h3g34haD4y0221CxZoGulyscow1d4fTGa+LvBmkPpPhPTdPuN3nBGmf8A7auz/wBa9u8KeO2iI0zX25XkTens/wDjQG3xG7UlFFAEdekV53XolABRRRQB5vUlFFAEdekV53XolABRRRQB5vUlFFABRRRQB//T/biivRKKAPN69IorzegD0iivO6joAKkr0SigDzevSKK83oA9Iorzuo6ACpK9EqtLLFbwvNMwWNR17AUAeXa5q0Ok2n8P/TOpfAdpKIbjXLv/AI+9SavPdY1O48T6yqDpKyxQ/i2B/OvcLOCK0ijtIvuRqFX6CtDyaFT2tXn6G1FXEeMfB511bfWNJcWmt6XlraQYw4AJ8iX1jY9R27d89hXxZ+1v+2p4I/Zg0Y6fGF13xneqBZ6WjYxnpJORyo4/H25p06c6svZ0l9x6x7DaXlzIZPtVrLYXdswE1vKSSh9m+6Vbnay/I1aMN3X8xl7+15+0fe/E5fi0njC4/ttVCfZ8k6ebcHJg+zHIxmv0p+Dv/BTD4deKXh0f416efB+qNjGoWaNcaYSTg5GTPDX0dfIsTSjtzeh5dPG0p/5M/Un7XVX7XXJeF/FPhbx5pQ1vwTrtlr+nEZ+0WNxHcx/QmNm2tWvNDd1857M9D2gSy1z13NVv7JqH/POs7+w9W/2U/wB6sifaeZzN3NXPSjzZvKi3PJ/D8u5mrvJdD0+0hku9c1JY4/vfu/l2r7ua+T/ih+2z8CfhUJtL8N6kmsapnHk6UUuJsg8h7kEiPg1206FWrPlp6sr2569rWn3+liKO/Qb2jEn3lJwexUE7WrW8KeCbu8u4ta1+38uGFlkt7eRfmduqu6t91V/z7/hN8Xf2uPir8VJdumXT+FdHD74rexlYTD5h/rbkYZm4r7b/AGXf+Cgrao9t8O/2h7n5SfJs/EOe/U/bSTXt18jxNKl7Xful0PPp42lOfLfXufqrNz+9mqrN0q1KQR5vyyRuuVZeQQaoV8uep/dmd54Z1v8A1ek3Un/XOu8rwaH/AJ5Rbo5I2+Vlr6M8I68mtaYsrt/pSD96Petv755OEq+86E91sZFekUV5vWJ6x6RRXndR0AFSV6JRQB5vXpFFeb0AekUV53UdABUleiUUAed0V6JRQB//1P38ooooAK87r0SvN6AJKKKjoA9IooooAK87r0SvN6AJKKKjoA9IrmvFdtYahoV5pGp82+pRSWz/AElUg/pXS182fF74x+DvB/iG28K65NOtyYVuP3MPmgCRiozkj0oAwPgy9yynRtTx9u8KyzWFwAcgiI/uHHt5JRq+iq+efh/qVqPijrrWgzaeJdFstUjxu+/bO1v/AL25l8uvTvG/jfRfhl4J1nx54mn8jTdFtpLmWgz9mfN37Zv7Wek/sx+BimlkXvjPWwRp9r1OOhlkH8IXP+e38x+va9r3jDXb3xT4pvX1TWNUcy3FxKclyOBwOBwK7f4zfFrxJ8dviVq/xJ8UMVGoyEW4HS3tskiIfTNeb+V71+05Tlv1OnzS1k1qz4jMsd7SXJHYq0Vq/ZP8/wCRUX2SvfPnvaBoWsa74Xv/AO1PDGp3ej3qfduLKeS3mX6PGysK+lPDn7bn7U3hhy1n8QLi9VsZXU4Le+Jxxy80Tua+YvJWoKmphKVX+LFM9GniakPhbR92/wDDyP8Aaj/1U15osn+9pv8A9euS139vX9qjW0W3i8T2+nbQATa6fbjOP+uiOfzr4/orh/s3B/8APtfcdbx1f+dnb+M/if8AEz4huT468VanrgY/6q6u5XhH0jLFVriPJ8n91FtjjqSrwhXvXpU6cIe7BJLsjz51+sm2ZtAiMp8qb50etX7J/n/Iqp5XvUnP7Q/UD9hz9rifRbiy+BXxQvdul4WHR76YcQYGBZvj/P8AT9dZv+eUtfygSQc/+zV+9/7Fnx7f4zfDYaF4knJ8VeFcWt0DjNxCR+5n47mvzXP8t9l/tNLZ7n3WXY32v7uW6Wh9lWn+t8qX93HIrbm/uqtdb8C0L2lz44vCGfxnIJYjnP8AokGUtP8AvpN7da8c8b3c3/CK6iunlhdXi/ZY/wDfuCsX9a9G8W/F74efDC9svC17JOp0eK3hAhtXIwF45wAeMZxXwJ7Xs/f9r1Z9Z153XfAg/McFPvA157QaElFFR0AekUUUUAFed16JXm9AElFFR0AekUUUUAFFFFAH/9X9uKKKKAI69IrzuvRKACiiigDzepKKKAI69IrzuvRKACiiigDzevnT4i6/8SrHxtdp4b0exutL2Q4mml2fwLn0r6Pr4n+M32AfFHUt3iy40lttp/o3m/8ATBaAO88OahcH4reD5bn91cXdnqdpLtbcqkwrNgP8u5VZa+Jf+Crvxcn07wt4c+DOlTNnWJPtl8cf8sbfoM/U19YeAp2vPil4KVmabyjfHfld3No65LDk9K/Gr/gof4gXxB+1Rripn/iUWdra+3I8+vqMjoe1xn+HU4MxqclA+J4oq6C0tKz7TpXaWUG6J5f+eYZq/YD8hxVdwNzQPBHiTxE7RaBpk+okfe+zRmXGOOwrL1nwxqmiXJsdXtJbK47xzoY3H/ASc1+t/gLQNP8AC3g7StG0wAAwRyueR5ksqLluc9cV5d+0loGn6x8O5dbvdou9Kli8qQ85EsiIV/HNfQTy7koe0ufzpgvElYjNlgvZWg5cqfXfTQ/LC7irEm6V3urWhFcbNXjn9IYSfOZ9FFSw9K5z1DTgiB6nFdBBZljvf5Uqnp0Q7dK+sf2bPDGl6149MmpoGXSLd7pEIyDKrqqk/wDfVdkafNNQjuz4vOszjgcNPESu1FXPGJ/hf46i0ga1deH71LIru89rdwmPqeK4Sez27mQYQ4/Cv23EkmcGRq/Mf4+eGNN8P/EjV7HTl8q3mWK4Cf3BLGpP6mu/FYF4e0k73Z+S8JcePOMTPD1KXK0rq3qj5Vlir3/9kv4lv8Kfj54c1Nm26drEg0q+OM/ubwgD06SivGNRBGK5a586BhNESkkeGVh1BHKmvCr0IVaTpS2eh/RuCr+8nE/qJ8Wf8ffhr/sO2H/kJ/NrW8aeLfih9ruD4W0fTr2yGMG4mbefX5B92vOJfEP9t+Gfh14r/wCf+5067/7/ANpWH43m067u5PtnjO70n/p2jnT+5/30tfzyfqp926cJpdIsLq7QCc2sBk/3yik4/GvVK8g0P/kWNE/eef8A8S+05/v/ALlea9foAKKKKAPN6koooAjr0ivO69EoAKKKKAPN6koooAKKKKAP/9b9uKK9EooA83r0iivN6APSKK87qOgAqSvRKKAPN69IorzegD0iivO6joAK+J/2g/s+m/Esg6OL0Xtjbzb8L1y6f0r9IK+Kv2vNO+yQ+H/FcTHdG0tmw7fvBuQ/nmgDzn4Is198UIbtcY0vTJic/wDTbbH/ACr8kP25PBaH9pHxHqCv5M99DaykewiEI/8ARdfsN+zjYhdP1jxFOuJdRkSJD6w24J/8eZ6+Lv8Agot8Opf7Z0P4lWY/c82d1/NK+u4cnCGM/A+azzn+p/u/sn5If8I/rNocPD5y+qjP9a6K0V/JeKUeW6K3ytXVWldHbmO6i2XUayZUr8yqeK/a/Z/yH4Risyl9tJ+Z+m2mjGlaeOwtLbH/AH6WvMfj3j/hUus/79tn/wACBXaeB9dsPE/hbT7zTDkRxRxyrnmN0UBhtHbJrzH4/wCrWX/CEXPhlJAdQ1KSL5c/cSKRJGJHvivsJ1P9l+R/EuT4Sp/btKlZ3U1f5PU/NzWwa4S6GRXqWqeGdQ/gnjf/AHtw/pXFXXhPWfWH/vv/AOvXwvsz+9cDWpcvxI4upYelbv8Awh+r/wB1f+/i/wDxVW4vCWs9kSP/AIH/APXo9mfR/WqH85a0ok9a+0v2WuPGeqH/AKh7/wDo6OvknT/DGqE4Lxf99N/hX1B8AtTtvBfi9p9RuF8q9ga2LkEBPnVlJJ/h3LXfhv4kJS2ufkvGNquW16dPVuOyPvcHaTX57/tMqD8SL8+ltaf+ihX6G8QRGSYqiIMszHAA9S1fA3xW13SfEnjO/wBVswDEBFGjY+/5cYXI/Kvosy9+Kh5n80+HTnDMqlVRulHdeqPke407UL7/AI9rZmH97GFqCbwb+6f+0J/4f+WVeu3c1dZ8H/A7/Eb4oaB4WVS1utwtxdAAE/ZYW3yDn1Ar5Spy0oOrV2R/Y+ExderONOlZNn7AXek/2J8HPDQ+b/inoNJ/8gJ5VeceJtWtZppPN0X7f5i7fM2pX01qWkjxDZ3ei/8AP7C8P0yuM181fC+xuPFXxO8OeF9uVW8U3QHeOz/euP8AgQFfzUf0OfpfDDFp+nWmnf8APrbRQV6fRXm9AHpFFed1HQAVJXolFAHm9ekUV5vQB6RRXndR0AFSV6JRQB53RXolFAH/1/38ooooAK87r0SvN6AJKKKjoA9IooooAK87r0SvN6AJKKKjoA9Irzf4p+CIfiD4D1Xwq2PNuYyYWP8ADMvKn8/516RRQB8heFbGLwtp+naNbZxZJ5OfXuxOP4mapviX4F0b4o+C9Q8IaygMN6gByM8ggg4PdWVGVq9K8e6Cbe5/tq2/1U3+sPoa5u0l/cx10duU8Wh8cqFT8T+c74nfDfxJ8JPFNz4Q8SJld7fZ5trKlxCCQrjPriuTiu6/oW+K3wk8F/GbQX0bxfbAEj93MPvxP7V+P3xa/ZG+KHwvmlu9ItW8T6ICSHtQTcIM/wAcIyfyr9iyniCliP3Vf3Zfmflmc8OVaP72j70fyPB7TV57OXNpPJA//TMsn8jUU14T+8lLPI/3mcsWP1Y1zBuiPMil/dvG21lb5WVvQpSeb7V90fnP1X3+bqW5ZayZal86qdZndTphViq9FBqa8M1a0N3XNVYoOWpT5zsDrV6bX7JLdyyWqfdjLsU/756VmTXdYn2vnzpdsdeh+BfhX8RPihPnwXo8s0ByBdEGK1zzwZsYzxWdSvClDmqtJLqysLl0pz5acW32RwUxmuJ44IkaSSTaI40XknooCjlmav1l/Za+Bz/C/wAPTeJ/FMX/ABU+sKpdO9vCeREO2T/y0rQ+Cn7LfhX4VhfEmtt/bnifOfOPMNvxj/R16/jX03X5DnmefWf3FA/bcjyL6p++rGrof+tku/8AO6u1+Evwr0/S/iJ4i+KXBOqRJbWsfUxjObgnv87BD+BrK8N6LcX0sWm25Yg/fP8Acr6isLWGwtIrO2G1IlwBXwp9PQ96tI0a87r0SvN6zPUJKKKjoA9IooooAK87r0SvN6AJKKKjoA9IooooAKKKKAP/0P24ooooAjr0ivO69EoAKKKKAPN6koooAjr0ivO69EoAKKKKAPN6koooAilhh8mT92v3W/4EtcXrnh1/Dt0cbjYS/dbPIPoa7mu6nghuIjHOodD1BoM6kL2l1R840vm/L5UoV0f7ytyK7fX/AABc26eZ4bbC/wDPE9K8zwR+5mDRyIcMrDDD6rQaHmXjr4G/CT4lZPinw5bzTsMG4C+XPj/rou1sV8q+J/8Agnr8OmfPhbxHfaOvoQLjn9K+96K9ihmWJw/u05tHBXy7DYj+JBM/KDU/+Cd/xFiQnRvFWmXq5+7cRTQcf8BD1w97+wh8fV/1P9jXP/b5KP8A2jX7J03zfavc/wBY8d9pp+qR4n+rmB/la9Gfiv8A8MQftD5/5B+nY/7CEX+NXIP2G/2gSObbSofrfH+iV+y1VfN9q2/1nx3937mZ/wCrOB/vfefkzpn7AfxbnP8AxOdc0ayT/Ye4l/nCtem6N/wT50vaB4p8a3DNnrZ2qw8fi8tfofVeuOfEeOn9u3ojphkGBh9j8z528LfsrfA7whlToA1hWOcam4uOg9CMfpXv8Pk2cP2W0jWCMDgKAqgegUU6qU0v/PWvmK9erV/iyZ9DToUqX8JL5C1oaNpd1rOpxWNqn+ff+6ta/hrwXr/ipBJax/ZrP/n4lB5/3R/F+FfS3hfwlpHhOxFnpqZcgeZK335CO5/+tWBocho2lQ6Va9BnrJJ/h/srWtRRQVT9z3I7Ijr0ivO69EoJCiiigDzepKKKAI69IrzuvRKACiiigDzepKKKACiiigD/0f24or0SigDzevSKK83oA9Iorzuo6ACpK9EooA83r0iivN6APSKK87qOgAqSvRKKAPN69Ioryuaab93p2nxrJeSf98qvqaAPVKxtS0LStVXF7Arn16GuJ1DwTYarpdzpl8vnTSIwEuW+RyvBT6NXzL8H/EHjnUNS1SK5tXm0qyWIR3U2R5rlV3gE/e2mgD0jxvZ6d4T0n+1oXkeOSSONo22blWTuXriP+Es07/pp/wB81Yu/itqcPxotvhN498OWwsPGltO+j6gkznJt0yba7GOuOmOuelWNX+EU2GPhPUAp7Wt5u2D2Sb5m20Ac9d+PNE/5e/tf/gNWJ/wtXwXj/j6m/wC/D1LeeDfHWlOyXWgXEkcYJ8y1KXA/BFZWrmbub/oIWlz/ANvNpPQB0P8AwtLwR/z9z/8Afio/+FqeB/8An7n/APAeuS/tHw7/AH7b/vipIdR0np8v/bCB/wD4igDp4fiL4ZY4tPtTE9hayVrHxFaS9BMmf4SmGrmYv7Wu/wB3aaTfyR/3mgeJf++5dtWv+Ee8Q/8ATHTf/I//AMTQBr/2t9qu4NPs9sfnt/y3+7t9TX1ponw08M6QA8sAvbjvJKM/kvQV8R+KvEGi/C/wsusDQ/8AhKtb1zUbbSNIsZZmJuLyZch5f4vLjxz/AJI+pvBo1bT7K1sNbtYLdtiAi1d5YIpgORF5uD5IoA97or5t+F8H/CVP4i8U6qwuAb6W1tcFv3MEWCOpxzmu8uraXRDtut1xZP8ALHI33o29D/eoAvVJXolFAHm9ekUV5vQB6RRXndR0AFSV6JRQB5vXpFFeb0AekUV53UdABUleiUUAed0V6JRQB//S/fyiiigArzuvRK83oAkooqOgD0iiiigArzuvRK83oAkooqOgD0iiiigDK1W/TS7MzkdOBWRoOniwtPtLD/SbrrXPz339seIwP+XWw6/Wuu+10EXKevXIsdI1G9PVIJiPqEyK/Or9nv4pa5a/tDan8L7u7Enh6fTJpY4DwYryzNuMR/7LK0m73r7g+JuqR2PhC9a6xtUZl/64x/PJ/wCOrX5Pfs2Xq3vxR8T/ABPZT/o9rLb57C41O4Wb/wBFRV9vk+DpPLsbiqy+FJL/ABNnzGZYur9dwuGpXvKTbt/Kk/8AM+t/j3s/4XR8A/sX3f8AhJ58/THNfYv2Svhnwzc/8LE/ax8NoFD2fw70W81Mk/8AP1qH7lP0r78tK+IPqir9kpJfO/56N/n8K6f7JWTd0Acld+d/z0/z+Vc/dyzf89Grq7uufu6AONu/+BVzN3XWXdczd0AfP/xO/wCSg/A3/sarn/0nhr3L9pf4i6z4A+COo6x4YmNtrBuLSyWcDOBPMAfX/llzXz7+0RbzW3gay8VIuW8G6vp+rj8JQMfrVz48aonj74Ma/YaWBKRHBqlqSM4FpKk5PH8WwPXrZYqf1uj7b4ebU8vMfafU6nsfi5Xb1sfR37LGpvqfgErOwEkn2e6JB6mWFAx/76WvqB4Irm2eC5GQRhq/PH9iHxTHqPhkWLKf9Gd7fJ9z9oj/AMK/QLzfauvPcD9SzGvhpbRk/uvoYZPivrmBo1u6V/u1/EztFuTYzPoV22GT/Ve6+ldfXnfiESmFNVtP9fZMtdhpGoLqlil4owHr549lM1K87r0SvN6CiSiio6APSKKKKACvO69ErzegCSiio6APSKKKKACiiigD/9P9uKKKKAI69IrzuvRKACiiigDzepKKKAI69IrzuvRKACiiigDzes3W7s6fYPdDHz8fia1q898Y3ZluobCPpGu5vq9BzV6nLScuuyOm8NAix+0twZv8r+ldR9rrkoZT5Pk/7KrVuGX990/ioNadPkhynzh+194pvNI+F8ulaYR9t1w/YYxleQ4PnPjrt2ivg3wrquneCdA/ssMAIw9xcOAcSTAZZz7Yr139pXxu3jDxnqUqqR4X8Fag+gfaiVCjU/KSa5GOuQBXlHwo+Hd18dvFMViwf/hCtLkWTVb7ODNggm2iODyRXpfXav1b6p9m99DH6rT9v9Z+1bl+Vz64/YxGmjQvEXjDVLiP/hJvGV8JjHjGLK3QCAD8z3r7vtK+a/8AhUmgWtwb7ws5slY5+zOWKIT/AHGzu217Z4VtLwD/AImE7fTzK6sXRwfJ7XDVPvPPwlfE/wDMTD5o9DF0fSsq7mrC1rXYtK5rzjUPi5oWnnF/a3Wf91f8a56OXYisrqH3GtTMsNS+0ehXdc/d15BqP7SXwxs/+Po33/gM9eb6l+1/8GbL93ENUuH/ALqWyj/0KVa9enw1m1T+HhZv0TOCpxHlUPjrxXzR73d1zN3XzJrH7Zfgsv8A8Szw5qLDHeWGDn8PNrybXP2tPGurkf8ACMaRaWAHOGD3s2PrgAV9NhPD7PsR/wAuORd5M8SvxxktL4a3N5RTPsfXdBtfEmh6joWp4+xX1vLbzAdkkUhiW9wa+B/BfjS60LSz4buLkXdzoEklr5sZV0lRGYJj/gIrQHgj4/fFIf8AFWTXP2A/9BKT7NB/34q54y+Bt94J0JPEnha5k1jULL/j+twi4lhP/PIDLblrhzzIMHl1Dlli4zq3tyxu0l1OrKs8xOYV/cw0oUraSlbXtodN+y7qa+B/jA+hWJA0TxGGFuSSPs91CGlRD6rjeq1+sP2uvxB8K64dZ1rS38ITqusLcRSW6E8I6MpBKntxX7W6j/os3lf7VfHYvH1cTP2tbWVrfcfV4TCUsPF06W1729dzQmm/1kX+y3/fNcHoF1t1C50y767v1rb+11x2rSCy1qPUwMDhv6NXCZYv3LVT0mvSK87/AOmsX7yORdy/7rV6JWZ3hRRRQB5vUlFFAEdekV53XolABRRRQB5vUlFFABRRRQB//9T9uKK9EooA83r0iivN6APSKK87qOgAqSvRKKAPN69IorzegD0iivO6joAli/4DXkP2v7XrX2uX/no1fQ2t3C2mlXkv9yJzj8K+aLT/AJZ1vT6yPKxX8WEfmdl9rrz34wfE/wD4VJ8MtY8aZUaoUNrpiEHEuoXAPk5wDxkV0P2vyf8AXf8ALOvz88c6zcftEfHbTfCGkqbjwx4KkIJ4KTagMiZz1/1Z/dVgeqe3fs8fD630H4Pto/imzTUf7euJL68+1IsvnPJ1L569K+mtIWz0y0h0nSbSKxsoF/dw26LEg+gA21na3pMXh6LSdP8AL/5dqihl9KAO4irW+11w/wBrrQ+10AdPN9kl/wCPuNZP+A1xureB/CGrgZsm/CV0/ka1/tdQ/a67aGLr0v4U3H0ZzVMJQq/xIJ+qR5Dqf7P/AMML47mjvm4xj7Ux/nmuN/4Za+Cef+PG+nk/6aX/AP8AXr6A+11kzXde9T4lzeOkMTP72eH/AKv5Z/0Dxv5pHkNp8DfgzpSFE8K24Vv+fiWaf9JXcV1lpZaPoUf/ABJNNttO/wCvWFIvzwBWtNNXPXcteXisxxmL/wB5rSn/AInc9ahgMNh/4NOMP8KsVLuf/lrLukkrnppq0buuelryDvMm10fQrPVG1a0023gvZ3TzJ0iQSN8y9Xxur7+8ZWQ8mLUR/Cyo/wDuk18Gdo/95a+7NQhhl+12c3+rkVlagfkcH9rrK1b995cv/PNmWqSm5sb+60W+5urFsj/rn/8AEtUUsv8AyyoOfF/wn6HpGh3X2rRoPM++gKH8K9cwAea8u+Gk+be/syeEkRwPd1+b9RVynUJws+ekp+R6RRXndR0jpCpK9EooA83r0iivN6APSKK87qOgAqSvRKKAPO6K9EooA//V/fyiiigArzuvRK83oAkooqOgD0iiiigArzuvRK83oAkooqOgDe8Zc+GdR/65Gvnf/pjX0/q1oL7Tp7Un76kV+fHxg8a+NPBSPoPhvw5cXuqAjEuFMGO9b039lni4uE/axqxTdux55+0D8W7jQLeHwL4Ll2+I9YzDAB1iycC46dc/Kn9569a/ZV+C1p8OPB0F3dx/6XtWuM/Zr/Zl1tfEMnxO+J2671a7bzK+57TyrS0jih2+XHtWsD2jiPGkJmJC/wDLGNX/AFavMobuvY/EDZubWUYdJFK/98t/9evFtctP7D1H/p3n3eXVf3jmp1PfcJd7o3ftdWvtdcb9rrR+1/5/yak6Tp/tdQ/a6577X/n/ACaPtf8An/JoA1/tdZv2us/7XVSa7oAmllrDmlo+1/5/yaxJZaAC7rJqSo6AIf8Alun+8lffN1/rpK+F9DtDqGt6dYf897mEH6F1Br7hu5f9Z937zVrUPFwNf2tWdT0SOc+KnhnULq2g8W+H136ppAz5Z5E0OcsuPUckfj7V5Tp+o2uq2yX1icxOvPt6g/7S19cJxk14D4o+FupWutS654HePF9/x92MzbIz/wBNIn2tses2elL+HY2fhbxfaj/1yh/rXTVZ8G+HH0C0klvWBublhk54wPuiqVKoThafJSUJbklFFR0HUekUUUUAFed16JXm9AElFFR0AekUUUUAFFFFAH//1v24ooooAjr0ivO69EoAKKKKAPN6koooAjr0ivO69EoAKKKKAPNf++az7vQ9Ju5vNu7RZJP92taigCLyYfJ/dRr92vSa87r0SgDgPH1l5nh83g+9YN5w/CvF5vsmq232W6+X+efUV9PvHuHQH5cc18v+I9Nl8Maw1iAwtjl7fvhPStaZ4uOXLL2p5pf2l1o0v2W5/wCAP6ioPtddxLNDdxfZLyNZI5PvK1cddeHs/vNKkWRP7jnkfRqPZm1DGw+GWjIPtdH2usSYXdn+6uo2T/eHFVPtdZHq/wB+Opufa6p/a6yftdR+b7UCLX2us+iofN9qDOpXpUv4jSJqjqvSgEkQwozySMFVVGSS3CgV6NOn9uR8dj8y9r+6pXS6s9i+CGhHVfGg1ZcG20dD1/57Sqyfyr7XBz06CvNvhl4Mj8G+HYrWRMXlxiW4Oc5kIxgH0A4r0cYAI9a4qmp9Bl1D2VCzPO6koorM9Ujr0ivO69EoAKKKKAPN6koooAjr0ivO69EoAKKKKAPN6koooAKKKKAP/9f9uKK9EooA83r0iivN6APSKK87qOgAqSvRKKAPN69IorzegD0iivO6joAKkr0SigDzevSKK83oA9FwB9K5jxT4ZtPFGmGwujtYHKPjkGsWo6Bzpc3uvVM+ZNRXUNDujp+pJsmBP0I9Q38S1U/tCvs7WfD+keJLE2WqwLPHzjI5UnuPQ18x+Kvg14m0gNdeHJDq1uvOxiouP1AVq66dT+c+OxWBq0vep3a/FHBTahWHd3dZOrDUNKkFtqlrNZOeQJUZD+RArP8ANP8Az0rtPnPaFuWWqdO/75o/75rQyG0VF50H+qi+eST7qr8zNXo2gfC/xnr7hPsDWNsP+Wt0GiwPp95qzKp05T92Cbfkef8AI/66SN8q/wB6vqj4TfCuXSJV8U+KU/04/wDHvbn/AJY47n/ppXa+CfhNoXhEi+cfb9TyD5sn8B77B2ra/wCmstcVSp9iB9hgcu5P3tTfoj0SivO6jrkPpgqSvRKKAPN69IorzegD0iivO6joAKkr0SigDzevSKK83oA9Iorzuo6ACpK9EooA87or0SigD//Q/fyiiigArzuvRK83oAkooqOgD0iiiigArzuvRK83oAkooqOgD0iiiigArzuvRK83oAkooqOgD0iiiigCpLDDOmJkDfhmvKz4X8MSnzptGsZH9fs8f+Fet/PXndNjUIfbVzH/AOES8J/9AKx/8Bov8Ki/4RDwru83+w7H/wAB466Go6f3mPLDsdjaaPpumjGn2cNp/wBcogP5AVr0UVJqFed16JXm9AElFFR0AekUUUUAFed16JXm9AElFFR0AekUUUUAFed16JXm9AElFFR0AekUUUUAFFFFAH//0f24ooooAjr0ivO69EoAKKKKAPN6koooAjr0ivO69EoAKKKKAPN6koooAjr0TGa8/rrr29EfAp/HpExqVoU4c8jS3Kud1Zbara44YD/P0rjdR1auTu9W/wCWsle3Qy5z1kfAY7iaFL3YI1/7Ri/2ai/tAf7NcDd635Vcdd+Jpf8AnpX01DI+c+HqcVYmXwnsf28f7NdAfFS93FfJt14wm9awZfG83/PSvoI8MNnB/buMn1Psn/hK0/57D8v/AK1H/CVp/wA9h+X/ANaviX/hPB/z0/z+VW4vHn/TQf5/Cur/AFVY/wC2cYfW/wBvH+zVv+0B/s18vWnjGb/npXW2niuavGr8O8hpT4jxkOrPef7Ri/2a9GOr2pH3sV812niGuytNW96+exGU8nke3Q4vq/DV1Pc1ljboalIxXl1pq1dhp+oAjBr52thJwP0LBZ5SxD5WrM5upKIaK88+qI69IrzuvRKACiiigDzepKKKAI69IrzuvRKACiiigDzepKKKACiiigD/0v24or0SigDzevSKK83oA9Iorzuo6ACpK9EooA83r0iivN6APSKK87qOgAqSvRKKAPNf++a6LUbWukVhXnXkj/ZranU5NTzsVhfbQ5ZGPf2sv+1XM3dpL/qq7iW0irPl0ivpsPmMND8ozLhyt8UdTyHUdPlrgtQ0ib0avqS78PAisqXwzEf+WdfWYXOYwsfFVMmxMOh8c3+hXX+1muUu/DF3X2t/wh1p/wA8653/AIQ219K+socSJGH1Wv5nxd/wh0vq1aFr4Yu4jX17/wAIRaen+fzo/wCEItPT/P516T4qTQvZ1+zPnDT9Emx/FXbafpMuK96h8E2v+1WrD4Zi/wCefFfO1+IIzH9QrT6Hk+n6fL0ru7S0uK7mHw9j93F0qpDpI/1tfI180jPqejQyDFVehFaWk3+1Xd2FpJ/tVzUWnw/7NXPKhz+5218rXxfPoj9Ty3I/q/vVRIf9VUteiUV4Z+gHm9ekUV5vQB6RRXndR0AFSV6JRQB5vXpFFeb0AekUV53UdABUleiUUAed0V6JRQB//9P9/KKKKACvO69ErzegCSiio6APSKKKKACvO69ErzegCSiio6APSKKKKACvO69ErzegCSiio6APSKj8qP8AuCpKKAKn2O3/ALled+VF/k//AFq9MBPQV51VKUvMzVGm/iRB9kio8qL/ACf/AK1W6jrXmfdmX1Wl/IjvPsVv/cqfyo/7gqWisDpCvO69ErzegCSiio6APSKKKKACvO69ErzegCSiio6APSKKKKACvO69ErzegCSiio6APSKKKKACiiigD//U/biiiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigCOvSK87r0SgAooooA83qSiigAooooA//V/biiiigAr0SvO69EoAKKKKAPO6KKKACvRK87r0SgAooooA87ooooAK9ErzuvRKACiiigDzuiiigAr0SvO69EoAKKKKAPO6KKKACvRK87r0SgAooooA87ooooAK9ErzuvRKACiiigDzuiiigAr0SvO69EoAKKKKAPO6KKKACiiigD/9k="""

if not TOKEN:
    raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN")

DB_LOCK = asyncio.Lock()
STATE_LOCK = asyncio.Lock()
users: Dict[int, Dict[str, Any]] = {}


def ensure_robot_asset() -> str:
    if not os.path.exists(ROBOT_IMAGE_PATH):
        try:
            raw = base64.b64decode(ROBOT_IMAGE_B64.encode("ascii"))
            with open(ROBOT_IMAGE_PATH, "wb") as f:
                f.write(raw)
        except Exception as e:
            logger.exception("Không tạo được file robot: %s", e)
    return ROBOT_IMAGE_PATH


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    return conn


async def run_db_work(fn):
    return await asyncio.to_thread(fn)


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_state (
                chat_id INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL DEFAULT (unixepoch())
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                raw_value INTEGER NOT NULL,
                label TEXT NOT NULL,
                created_at INTEGER NOT NULL DEFAULT (unixepoch())
            );

            CREATE INDEX IF NOT EXISTS idx_history_chat_id_id ON history(chat_id, id);
            """
        )
        conn.commit()


def prune_history(conn: sqlite3.Connection, chat_id: int, keep_limit: int) -> None:
    if keep_limit <= 0:
        return
    row = conn.execute(
        "SELECT id FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
        (chat_id, max(0, keep_limit - 1)),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM history WHERE chat_id = ? AND id < ?", (chat_id, int(row["id"])))


async def append_history(chat_id: int, items: List[Tuple[int, str]]) -> None:
    if not items:
        return

    def _work():
        with db_connect() as conn:
            for raw_value, label in items:
                conn.execute(
                    "INSERT INTO history (chat_id, raw_value, label) VALUES (?, ?, ?)",
                    (chat_id, int(raw_value), label),
                )
            prune_history(conn, chat_id, MAX_KEEP_HISTORY)
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)


async def load_history_rows(chat_id: int, limit: int = HISTORY_ANALYSIS_LIMIT) -> List[Tuple[int, str]]:
    def _work():
        with db_connect() as conn:
            if limit and limit > 0:
                rows = conn.execute(
                    "SELECT raw_value, label FROM history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                    (chat_id, limit),
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = conn.execute(
                    "SELECT raw_value, label FROM history WHERE chat_id = ? ORDER BY id ASC",
                    (chat_id,),
                ).fetchall()
            return [(int(r["raw_value"]), str(r["label"])) for r in rows]

    async with DB_LOCK:
        return await run_db_work(_work)


def new_state() -> Dict[str, Any]:
    return {
        "values": [],
        "labels": [],
        "total": 0,
        "low_count": 0,
        "high_count": 0,
        "last_prediction_label": None,
        "last_prediction_conf": 0,
        "last_prediction_result": "CHƯA RÕ",
        "prediction_total": 0,
        "prediction_hits": 0,
        "prediction_misses": 0,
        "current_correct_streak": 0,
        "current_wrong_streak": 0,
        "max_correct_streak": 0,
        "max_wrong_streak": 0,
        "model_accuracy": {"pattern": 50, "structure": 50},
        "last_note": "",
        "last_structure": "CHƯA ĐỦ DỮ LIỆU",
        "last_mode": "NORMAL",
        "last_model_predictions": {},
        "last_gate_status": "CHỜ",
        "last_gate_reason": "Chưa kiểm tra",
        "last_detected_pattern": "",
        "last_detected_hint": None,
        "cooldown_active": False,
        "cooldown_reason": "",
        "last_relearn_note": "",
        "last_resume_note": "",
        "last_relearn_snapshot": "",
        "last_relearn_total": 0,
        "pattern_confirm_sig": "",
        "pattern_confirm_count": 0,
    }


def _safe_tail(seq: List[Any], limit: int) -> List[Any]:
    return list(seq[-limit:]) if limit > 0 and len(seq) > limit else list(seq)


def trim_state_memory(d: Dict[str, Any]) -> None:
    d["values"] = _safe_tail(d.get("values", []), RECENT_CACHE)
    d["labels"] = _safe_tail(d.get("labels", []), RECENT_CACHE)


def rebuild_counters_from_labels(d: Dict[str, Any], labels: List[str]) -> None:
    d["low_count"] = labels.count(LOW_LABEL)
    d["high_count"] = labels.count(HIGH_LABEL)
    d["total"] = len(labels)


def repair_state(d: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(d, dict):
        d = new_state()

    for k in ("values", "labels"):
        if not isinstance(d.get(k), list):
            d[k] = []

    if not isinstance(d.get("model_accuracy"), dict):
        d["model_accuracy"] = {"pattern": 50, "structure": 50}

    defaults = new_state()
    for k, v in defaults.items():
        d.setdefault(k, v)

    n = min(len(d["values"]), len(d["labels"]))
    d["values"] = d["values"][-n:] if n else []
    d["labels"] = d["labels"][-n:] if n else []

    trim_state_memory(d)
    rebuild_counters_from_labels(d, d.get("labels", []))
    return d


def trim_cache() -> None:
    if len(users) <= USER_CACHE_LIMIT:
        return
    overflow = len(users) - USER_CACHE_LIMIT
    for chat_id in list(users.keys())[:overflow]:
        users.pop(chat_id, None)


def map_value(n: int) -> str:
    return HIGH_LABEL if n >= THRESHOLD else LOW_LABEL


def opposite_label(label: str) -> str:
    return HIGH_LABEL if label == LOW_LABEL else LOW_LABEL


def get_key(update: Update) -> int:
    return update.effective_chat.id


def parse_input(text: str) -> List[int]:
    nums: List[int] = []
    for x in re.findall(r"\d+", text or ""):
        try:
            n = int(x)
            if n >= 0:
                nums.append(n)
        except Exception:
            pass
    return nums[:MAX_INPUT_NUMS]


async def load_state(chat_id: int, force_reload: bool = False) -> Dict[str, Any]:
    if not force_reload and chat_id in users:
        return repair_state(users[chat_id])

    def _work():
        with db_connect() as conn:
            return conn.execute(
                "SELECT state_json FROM chat_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()

    async with DB_LOCK:
        row = await run_db_work(_work)

    state = new_state()
    if row:
        try:
            state.update(json.loads(row["state_json"]))
        except Exception:
            pass

    state = repair_state(state)
    users[chat_id] = state
    trim_cache()
    return state


async def save_state(chat_id: int, state: Dict[str, Any]) -> None:
    state = repair_state(state)

    def _work():
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_state (chat_id, state_json, updated_at)
                VALUES (?, ?, unixepoch())
                ON CONFLICT(chat_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (chat_id, json.dumps(state, ensure_ascii=False)),
            )
            prune_history(conn, chat_id, MAX_KEEP_HISTORY)
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def current_streak(labels: List[str]) -> Tuple[Optional[str], int]:
    if not labels:
        return None, 0
    last = labels[-1]
    streak = 1
    for i in range(len(labels) - 2, -1, -1):
        if labels[i] == last:
            streak += 1
        else:
            break
    return last, streak


def run_length_encode(labels: List[str]) -> List[Tuple[str, int]]:
    if not labels:
        return []
    out: List[Tuple[str, int]] = []
    cur = labels[0]
    count = 1
    for x in labels[1:]:
        if x == cur:
            count += 1
        else:
            out.append((cur, count))
            cur = x
            count = 1
    out.append((cur, count))
    return out


def recent_ratio(labels: List[str], window: int) -> Dict[str, float]:
    tail = labels[-window:] if len(labels) > window else labels[:]
    if not tail:
        return {LOW_LABEL: 0.5, HIGH_LABEL: 0.5}
    c = Counter(tail)
    total = c[LOW_LABEL] + c[HIGH_LABEL]
    if total <= 0:
        return {LOW_LABEL: 0.5, HIGH_LABEL: 0.5}
    return {LOW_LABEL: c[LOW_LABEL] / total, HIGH_LABEL: c[HIGH_LABEL] / total}


def alternating_tail(labels: List[str], window: int = 6) -> Tuple[bool, float]:
    tail = labels[-window:] if len(labels) >= window else labels[:]
    if len(tail) < 4:
        return False, 0.0
    changes = sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])
    ratio = changes / (len(tail) - 1)
    return all(tail[i] != tail[i - 1] for i in range(1, len(tail))), ratio


def entropy_score(labels: List[str], window: int = 20) -> float:
    tail = labels[-window:] if len(labels) > window else labels[:]
    if len(tail) < 4:
        return 0.0
    c = Counter(tail)
    total = len(tail)
    ent = 0.0
    for v in c.values():
        p = v / total
        ent -= p * math.log2(p)
    return ent


def volatility_score(labels: List[str], window: int = 12) -> float:
    tail = labels[-window:] if len(labels) > window else labels[:]
    if len(tail) < 4:
        return 0.0
    changes = sum(1 for i in range(1, len(tail)) if tail[i] != tail[i - 1])
    return changes / (len(tail) - 1)


def detect_repeat_block(labels: List[str], max_block: int = 3) -> Optional[Dict[str, Any]]:
    tail = labels[-12:] if len(labels) > 12 else labels[:]
    for block in range(1, max_block + 1):
        if len(tail) >= block * 2:
            a = tail[-(block * 2):-block]
            b = tail[-block:]
            if a == b:
                return {"name": f"LẶP KHỐI {block}", "detail": f"Khối {block} mẫu gần nhất đang lặp",
                        "score": min(78 + block * 4, 92), "hint": a[0] if a else None}
    return None


def detect_motif_repeat(labels: List[str], max_motif: int = 8) -> Optional[Dict[str, Any]]:
    tail = labels[-40:] if len(labels) > 40 else labels[:]
    if len(tail) < 4:
        return None

    best: Optional[Dict[str, Any]] = None
    for m in range(1, min(max_motif, len(tail) // 2) + 1):
        motif = tail[-m:]
        reps = 1
        idx = len(tail) - m
        while idx - m >= 0 and tail[idx - m:idx] == motif:
            reps += 1
            idx -= m

        if reps >= 2:
            if m == 1:
                name = "BỆT"
                hint = motif[0]
                score = min(70 + reps * 6, 95)
            elif m == 2 and motif[0] != motif[1]:
                name = "XEN KẼ"
                hint = opposite_label(tail[-1])
                score = min(76 + reps * 4, 94)
            else:
                name = f"LẶP MẪU {m}"
                hint = motif[0]
                score = min(72 + reps * 5, 94)

            cand = {"name": name, "detail": f"Mẫu {m} lặp {reps} lần", "score": score, "hint": hint}
            if best is None or cand["score"] > best["score"]:
                best = cand
    return best


def detect_explicit_pair_patterns(labels: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if len(labels) < 4:
        return out
    a, b, c, d = labels[-4], labels[-3], labels[-2], labels[-1]
    if a != b and a == c and b == d:
        out.append({"name": "1-1", "detail": "Mẫu luân phiên 1-1", "score": 90, "hint": a})
    if a == b and c == d and a != c:
        out.append({"name": "2-2", "detail": "Mẫu chia cặp 2-2", "score": 86, "hint": a})
    if len(labels) >= 6:
        t = labels[-6:]
        if t[0] == t[2] == t[4] and t[1] == t[3] == t[5] and t[0] != t[1]:
            out.append({"name": "XEN KẼ SÂU", "detail": "Luân phiên đều trong 6 mẫu gần nhất", "score": 94, "hint": t[0]})
    return out


def detect_run_cycle(labels: List[str]) -> Optional[Dict[str, Any]]:
    runs = run_length_encode(labels)
    if len(runs) < 4:
        return None
    a1, l1 = runs[-4]
    b1, m1 = runs[-3]
    a2, l2 = runs[-2]
    b2, m2 = runs[-1]
    if a1 == a2 and b1 == b2 and l1 == l2 and m1 == m2 and a1 != b1:
        return {"name": f"CẦU {l1}-{m1}", "detail": f"Chu kỳ 2 khối lặp: {l1}-{m1}",
                "score": min(82 + (l1 + m1) * 2, 95), "hint": a2}
    return None


def detect_bias(labels: List[str]) -> Optional[Dict[str, Any]]:
    if len(labels) < 12:
        return None
    r6 = recent_ratio(labels, 6)
    r12 = recent_ratio(labels, 12)
    r24 = recent_ratio(labels, 24)
    gap6 = abs(r6[LOW_LABEL] - r6[HIGH_LABEL])
    gap12 = abs(r12[LOW_LABEL] - r12[HIGH_LABEL])
    gap24 = abs(r24[LOW_LABEL] - r24[HIGH_LABEL])

    if gap6 >= 0.50:
        winner = LOW_LABEL if r6[LOW_LABEL] > r6[HIGH_LABEL] else HIGH_LABEL
        return {"name": "NGHIÊNG NHẸ", "detail": f"Đuôi 6 nghiêng về {winner}", "score": 72, "hint": winner}
    if gap12 >= 0.35:
        winner = LOW_LABEL if r12[LOW_LABEL] > r12[HIGH_LABEL] else HIGH_LABEL
        return {"name": "NGHIÊNG", "detail": f"Đuôi 12 nghiêng về {winner}", "score": 78, "hint": winner}
    if gap24 >= 0.25:
        winner = LOW_LABEL if r24[LOW_LABEL] > r24[HIGH_LABEL] else HIGH_LABEL
        return {"name": "XU HƯỚNG", "detail": f"24 mẫu gần đây nghiêng về {winner}", "score": 80, "hint": winner}
    if gap24 < 0.10:
        return {"name": "CÂN BẰNG", "detail": "Hai phía gần như ngang nhau", "score": 65, "hint": None}
    return None


def detect_reversal(labels: List[str]) -> Optional[Dict[str, Any]]:
    if len(labels) < 12:
        return None
    first = labels[-12:-6]
    second = labels[-6:]
    if not first or not second:
        return None
    c1 = Counter(first)
    c2 = Counter(second)
    d1 = c1[HIGH_LABEL] - c1[LOW_LABEL]
    d2 = c2[HIGH_LABEL] - c2[LOW_LABEL]
    if d1 == 0 or d2 == 0:
        return None
    if (d1 > 0 > d2) or (d1 < 0 < d2):
        return {"name": "ĐẢO CHIỀU", "detail": "Hai cụm gần nhất đang đổi hướng", "score": 84,
                "hint": HIGH_LABEL if d2 > 0 else LOW_LABEL}
    return None


def detect_all_patterns(labels: List[str]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    for item in (
        detect_motif_repeat(labels, 8),
        *detect_explicit_pair_patterns(labels),
        detect_run_cycle(labels),
        detect_repeat_block(labels, 3),
        detect_reversal(labels),
        detect_bias(labels),
    ):
        if item:
            patterns.append(item)

    last, streak = current_streak(labels)
    if last in (LOW_LABEL, HIGH_LABEL) and streak >= 3:
        patterns.append({"name": "BỆT", "detail": f"{last} x{streak}", "score": min(68 + streak * 6, 95), "hint": last})

    alt, alt_ratio = alternating_tail(labels, 6)
    if alt and alt_ratio >= 0.80 and len(labels) >= 6:
        patterns.append({"name": "XEN KẼ", "detail": "Chuỗi đổi liên tục", "score": 88, "hint": opposite_label(labels[-1])})

    return sorted(patterns, key=lambda x: x.get("score", 0), reverse=True)[:12]


def build_report(labels: List[str]) -> Dict[str, Any]:
    c = Counter(labels)
    last, streak = current_streak(labels)
    alt, alt_ratio = alternating_tail(labels, 6)
    r6 = recent_ratio(labels, 6)
    r12 = recent_ratio(labels, 12)
    r24 = recent_ratio(labels, 24)
    ent = entropy_score(labels, 20)
    vol = volatility_score(labels, 12)
    patterns = detect_all_patterns(labels)

    if len(labels) < 4:
        structure = "CHƯA ĐỦ DỮ LIỆU"
        detail = "Cần thêm kết quả"
    elif patterns:
        structure = patterns[0]["name"]
        detail = patterns[0]["detail"]
    else:
        if alt and alt_ratio >= 0.80:
            structure = "XEN KẼ"
            detail = "Chuỗi đổi liên tục"
        elif streak >= 4 and last in (LOW_LABEL, HIGH_LABEL):
            structure = "BỆT"
            detail = f"{last} x{streak}"
        elif vol >= 0.65:
            structure = "CHUYỂN PHA"
            detail = "Nhịp đang đổi nhanh"
        elif ent <= 0.85:
            structure = "ỔN ĐỊNH"
            detail = "Mẫu gần đây khá đều"
        else:
            structure = "TRUNG TÍNH"
            detail = "Chưa có tín hiệu quá rõ"

    return {
        "total": len(labels),
        "low": c.get(LOW_LABEL, 0),
        "high": c.get(HIGH_LABEL, 0),
        "labels": labels,
        "last_label": last,
        "streak": streak,
        "alternating": alt,
        "alt_ratio": alt_ratio,
        "structure": structure,
        "detail": detail,
        "recent_6": r6,
        "recent_12": r12,
        "recent_24": r24,
        "entropy": ent,
        "volatility": vol,
        "patterns": patterns,
    }


def advanced_metrics(labels: List[str]) -> Dict[str, Any]:
    if not labels:
        return {"max_streak": 0, "r10_high": 0.5, "r20_high": 0.5, "momentum": 0.0, "noise": 0.0, "reversal": 0.0}
    max_streak = 1
    cur = 1
    for i in range(1, len(labels)):
        if labels[i] == labels[i - 1]:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 1
    last10 = labels[-10:]
    last20 = labels[-20:]
    r10 = safe_div(last10.count(HIGH_LABEL), len(last10)) if last10 else 0.5
    r20 = safe_div(last20.count(HIGH_LABEL), len(last20)) if last20 else 0.5
    momentum = r10 - r20
    changes = sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])
    noise = safe_div(changes, len(labels))
    reversal = abs(momentum) * 100
    return {"max_streak": max_streak, "r10_high": r10, "r20_high": r20, "momentum": momentum, "noise": noise, "reversal": reversal}


def extract_chart_features(labels: List[str]) -> Dict[str, Any]:
    if not labels:
        return {"trend": 0.0, "trend_label": "TRUNG TÍNH", "reversal_rate": 0.0, "smoothness": 0.0,
                "max_streak": 0, "last_value": None, "last_5_high": 0.5, "prev_5_high": 0.5}

    ys = [1 if x == HIGH_LABEL else 0 for x in labels]
    n = len(ys)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = 0.0
    if denom:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom

    trend = slope * 100.0
    trend_label = f"NGHIÊNG {HIGH_LABEL}" if trend > 0.08 else f"NGHIÊNG {LOW_LABEL}" if trend < -0.08 else "TRUNG TÍNH"
    reversals = sum(1 for i in range(1, n) if ys[i] != ys[i - 1])
    reversal_rate = reversals / max(1, n - 1)
    smoothness = 1.0 - reversal_rate
    max_streak = 1
    cur = 1
    for i in range(1, n):
        if ys[i] == ys[i - 1]:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 1
    last_5 = ys[-5:] if n >= 5 else ys[:]
    prev_5 = ys[-10:-5] if n >= 10 else ys[:-5] if n > 5 else []
    return {
        "trend": trend,
        "trend_label": trend_label,
        "reversal_rate": reversal_rate,
        "smoothness": smoothness,
        "max_streak": max_streak,
        "last_value": ys[-1],
        "last_5_high": safe_div(sum(last_5), len(last_5)) if last_5 else 0.5,
        "prev_5_high": safe_div(sum(prev_5), len(prev_5)) if prev_5 else 0.5,
    }


def build_relearn_snapshot(report: Dict[str, Any], adv: Dict[str, Any]) -> str:
    patterns = report.get("patterns", [])[:3]
    top = " / ".join(p.get("name", "") for p in patterns) if patterns else "TRUNG TÍNH"
    return (
        f"Cầu: {top} | Cấu trúc: {report.get('structure', '-')} | "
        f"Chi tiết: {report.get('detail', '-')} | Tổng: {report.get('total', 0)} | "
        f"Mượt: {adv.get('smoothness', 0.0):.2f} | Nhiễu: {report.get('volatility', 0.0):.2f}"
    )


def enter_loss_cooldown(state: Dict[str, Any], report: Dict[str, Any], adv: Dict[str, Any]) -> bool:
    if state.get("cooldown_active"):
        return False
    state["cooldown_active"] = True
    state["cooldown_reason"] = f"Thua chuỗi {LOSS_STREAK_LIMIT} liên tiếp"
    state["last_relearn_note"] = f"Tự học lại từ đầu bộ lịch sử sau chuỗi thua {LOSS_STREAK_LIMIT}"
    state["last_note"] = state["last_relearn_note"]
    state["last_relearn_snapshot"] = build_relearn_snapshot(report, adv)
    state["last_relearn_total"] = int(report.get("total", 0))
    state["model_accuracy"] = {"pattern": 50, "structure": 50}
    state["last_model_predictions"] = {}
    state["last_gate_status"] = "TẠM DỪNG"
    state["last_gate_reason"] = state["cooldown_reason"]
    return True


def clear_loss_cooldown(state: Dict[str, Any]) -> bool:
    if not state.get("cooldown_active"):
        return False
    if int(state.get("current_wrong_streak", 0)) != 0:
        return False
    state["cooldown_active"] = False
    state["cooldown_reason"] = ""
    state["last_resume_note"] = "Đã có tín hiệu đúng, mở lại phân tích"
    state["last_note"] = state["last_resume_note"]
    return True


def pattern_signature(pattern: Dict[str, Any]) -> str:
    return f"{pattern.get('name','')}|{pattern.get('hint','')}|{int(pattern.get('score',0))}"


def update_confirm_state(state: Dict[str, Any], report: Dict[str, Any]) -> Tuple[bool, str]:
    patterns = report.get("patterns", [])
    if not patterns:
        state["pattern_confirm_sig"] = ""
        state["pattern_confirm_count"] = 0
        return False, "Chưa có cầu rõ ràng để xác nhận"

    top = patterns[0]
    sig = pattern_signature(top)
    score = int(top.get("score", 0))
    total = int(report.get("total", 0))

    # nếu cầu mới yếu hoặc vừa đổi nhịp -> đợi thêm 1 mẫu để xác nhận
    need_wait = False
    reason = ""

    if score < CONFIRM_PATTERN_MIN_SCORE and total >= 8:
        need_wait = True
        if state.get("pattern_confirm_sig") != sig:
            state["pattern_confirm_sig"] = sig
            state["pattern_confirm_count"] = 1
        else:
            state["pattern_confirm_count"] = int(state.get("pattern_confirm_count", 0)) + 1

        if state["pattern_confirm_count"] < 2:
            reason = f"Đang bắt nhịp mới: {top.get('name','-')} ({score}%), đợi thêm 1 mẫu"
        else:
            need_wait = False
            reason = f"Đã xác nhận nhịp mới: {top.get('name','-')} ({score}%)"
    else:
        # cầu đủ mạnh hoặc dữ liệu chưa nhiều, cho qua
        if state.get("pattern_confirm_sig") != sig:
            state["pattern_confirm_sig"] = sig
            state["pattern_confirm_count"] = 1
        else:
            state["pattern_confirm_count"] = int(state.get("pattern_confirm_count", 0)) + 1
        reason = f"Cầu rõ: {top.get('name','-')} ({score}%)"

    return need_wait, reason


def prediction_gate(labels: List[str], report: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    if state and state.get("cooldown_active"):
        if int(state.get("current_wrong_streak", 0)) == 0:
            return True, "Đã thoát chế độ học lại"
        return False, str(state.get("cooldown_reason") or f"Đang tự học lại sau chuỗi thua {LOSS_STREAK_LIMIT}")

    total = int(report.get("total", 0))
    patterns = report.get("patterns", [])
    top_name = str(patterns[0].get("name", "")) if patterns else ""
    top_score = int(patterns[0].get("score", 0)) if patterns else 0

    # Chờ thêm 1 nhịp khi nhịp vừa mới hình thành/chưa đủ rõ
    if state is not None:
        need_wait, wait_reason = update_confirm_state(state, report)
        if need_wait:
            return False, wait_reason

    if total < MIN_PREDICTION_DATA:
        if total >= 8 and top_score >= CLEAR_PATTERN_MIN_SCORE and top_name:
            return True, f"Cầu sớm: {top_name} ({top_score}%)"
        return False, f"Chưa đủ {MIN_PREDICTION_DATA} dữ liệu"

    if not patterns:
        return False, "Không có cầu rõ ràng để phân tích"

    if top_score < CLEAR_PATTERN_MIN_SCORE:
        if total >= 10 and top_score >= max(72, CLEAR_PATTERN_MIN_SCORE - 10):
            return True, f"Cầu sớm: {top_name} ({top_score}%)"
        return False, f"Cầu chưa đủ rõ: {top_name} ({top_score}%)"

    return True, f"Cầu rõ: {top_name} ({top_score}%)"


def predict_pattern(labels: List[str], report: Dict[str, Any]) -> Dict[str, Any]:
    patterns = report.get("patterns", [])
    if patterns:
        primary = patterns[0]
        hint = primary.get("hint")
        name = primary.get("name", "")
        if hint in (LOW_LABEL, HIGH_LABEL) and name in {
            "BỆT", "XEN KẼ", "1-1", "2-2", "XEN KẼ SÂU",
            "LẶP KHỐI 1", "LẶP KHỐI 2", "LẶP KHỐI 3",
            "LẶP MẪU 2", "LẶP MẪU 3", "LẶP MẪU 4", "LẶP MẪU 5", "LẶP MẪU 6", "LẶP MẪU 7", "LẶP MẪU 8",
            "CẦU 1-1", "CẦU 2-1", "CẦU 1-2", "CẦU 2-2", "CẦU 3-1", "CẦU 1-3", "CẦU 3-2", "CẦU 2-3", "CẦU 3-3",
            "NGHIÊNG", "NGHIÊNG NHẸ", "XU HƯỚNG", "ĐẢO CHIỀU"
        }:
            return {"label": hint, "confidence": min(95, int(primary.get("score", 60)) + 2), "source": f"pattern:{name}"}

    if len(labels) < 4:
        return {"label": labels[-1] if labels else LOW_LABEL, "confidence": 50, "source": "pattern"}
    if labels[-1] == labels[-2] == labels[-3]:
        return {"label": labels[-1], "confidence": 66, "source": "pattern"}
    if labels[-1] != labels[-2]:
        return {"label": labels[-2], "confidence": 56, "source": "pattern"}
    return {"label": labels[-1], "confidence": 54, "source": "pattern"}


def predict_structure(labels: List[str], report: Dict[str, Any]) -> Dict[str, Any]:
    patterns = report.get("patterns", [])
    if patterns:
        top = patterns[0]
        hint = top.get("hint")
        name = top.get("name", "")
        strong_same = {"BỆT", "BỆT SỚM", "LẶP MẪU 1", "LẶP KHỐI 1", "XEN KẼ SỚM", "XEN KẼ", "XEN KẼ SÂU", "1-1", "2-2"}
        if hint in (LOW_LABEL, HIGH_LABEL) and name in strong_same:
            return {"label": hint, "confidence": min(95, int(top.get("score", 60)) + 1), "source": f"structure:{name}"}
        if name.startswith("CẦU ") or name.startswith("LẶP MẪU") or name.startswith("LẶP KHỐI"):
            return {"label": hint if hint in (LOW_LABEL, HIGH_LABEL) else (labels[-1] if labels else LOW_LABEL),
                    "confidence": min(92, int(top.get("score", 60)) + 1), "source": f"structure:{name}"}
        if name == "CÂN BẰNG SỚM":
            return {"label": labels[-1] if labels else LOW_LABEL, "confidence": 52, "source": "structure:balance"}

    if len(labels) < 2:
        return {"label": labels[-1] if labels else LOW_LABEL, "confidence": 50, "source": "structure"}
    return {"label": labels[-1], "confidence": 54, "source": "structure"}


def update_model_accuracy(state: Dict[str, Any], predictions: Dict[str, Dict[str, Any]], actual: str) -> None:
    state.setdefault("model_accuracy", {"pattern": 50, "structure": 50})
    for name, pred in predictions.items():
        old = int(state["model_accuracy"].get(name, 50))
        old = old + 1 if pred.get("label") == actual else old - 1
        state["model_accuracy"][name] = max(1, min(99, old))


def update_prediction_feedback(state: Dict[str, Any], actual_label: str) -> None:
    pred = state.get("last_prediction_label")
    if pred not in (LOW_LABEL, HIGH_LABEL):
        return

    state["prediction_total"] = int(state.get("prediction_total", 0)) + 1
    if pred == actual_label:
        state["prediction_hits"] = int(state.get("prediction_hits", 0)) + 1
        state["last_prediction_result"] = "ĐÚNG"
        state["current_correct_streak"] = int(state.get("current_correct_streak", 0)) + 1
        state["current_wrong_streak"] = 0
        state["max_correct_streak"] = max(int(state.get("max_correct_streak", 0)), int(state["current_correct_streak"]))
    else:
        state["prediction_misses"] = int(state.get("prediction_misses", 0)) + 1
        state["last_prediction_result"] = "SAI"
        state["current_wrong_streak"] = int(state.get("current_wrong_streak", 0)) + 1
        state["current_correct_streak"] = 0
        state["max_wrong_streak"] = max(int(state.get("max_wrong_streak", 0)), int(state["current_wrong_streak"]))


def meta_decision(predictions: Dict[str, Dict[str, Any]], state: Dict[str, Any], report: Dict[str, Any], adv: Dict[str, Any]) -> Dict[str, Any]:
    model_acc = state.get("model_accuracy", {})
    vote: Dict[str, float] = defaultdict(float)
    model_scores: Dict[str, float] = {}

    strong_patterns = {
        "BỆT", "BỆT SỚM", "XEN KẼ", "XEN KẼ SỚM", "XEN KẼ SÂU",
        "1-1", "2-2", "LẶP KHỐI 1", "LẶP MẪU 2",
        "CẦU 1-1", "CẦU 2-1", "CẦU 1-2", "CẦU 2-2", "CẦU 3-1",
        "CẦU 1-3", "CẦU 2-3", "CẦU 3-2", "CẦU 3-3",
        "NGHIÊNG", "NGHIÊNG NHẸ", "XU HƯỚNG", "ĐẢO CHIỀU",
    }

    volatility = float(report.get("volatility", 0.0))
    smoothness = float(adv.get("smoothness", 0.0))
    reversal_rate = float(adv.get("reversal_rate", 0.0))
    entropy = float(report.get("entropy", 0.0))

    for name, pred in predictions.items():
        label = pred.get("label")
        conf = float(pred.get("confidence", 50))
        acc = float(model_acc.get(name, 50))
        score = conf * (0.85 + acc / 120.0)
        score *= 1.05 if name == "pattern" else 1.02 if name == "structure" else 1.0
        if report.get("structure") in strong_patterns:
            score *= 1.08
        if smoothness >= 0.70:
            score *= 1.04
        elif reversal_rate >= 0.45:
            score *= 0.92
        if volatility > 0.80:
            score *= 0.90
        elif entropy < 1.0:
            score *= 1.03
        model_scores[name] = score
        vote[label] += score

    if not vote:
        return {"model": "none", "final_label": LOW_LABEL, "confidence": 50, "scores": {}}

    best_label = max(vote, key=vote.get)
    total = sum(vote.values())
    top = vote[best_label]
    top_ratio = top / total if total else 0.5
    agreement = sum(1 for p in predictions.values() if p.get("label") == best_label)
    strongest_conf = max((int(p.get("confidence", 50)) for p in predictions.values()), default=50)

    confidence = int(46 + top_ratio * 40 + (agreement - 1) * 4 + (strongest_conf - 50) * 0.15)
    if report.get("structure") in {"CÂN BẰNG", "TRUNG TÍNH", "CHƯA ĐỦ DỮ LIỆU"}:
        confidence -= 6

    confidence = max(0, min(confidence, 95))
    best_model = max(model_scores, key=model_scores.get)
    return {"model": best_model, "final_label": best_label, "confidence": confidence, "scores": dict(vote)}


def analyze_state_from_labels(state: Dict[str, Any], labels: List[str]) -> Dict[str, Any]:
    report = build_report(labels)
    adv = advanced_metrics(labels)
    chart_features = extract_chart_features(labels)
    adv.update(chart_features)

    resumed = False
    if state.get("cooldown_active") and int(state.get("current_wrong_streak", 0)) == 0:
        resumed = clear_loss_cooldown(state)

    relearned = False
    if int(state.get("current_wrong_streak", 0)) >= LOSS_STREAK_LIMIT and not state.get("cooldown_active", False):
        relearned = enter_loss_cooldown(state, report, adv)

    allowed, reason = prediction_gate(labels, report, state)
    state["last_gate_status"] = "CHO PHÉP" if allowed else "TẠM DỪNG"
    state["last_gate_reason"] = reason
    state["last_structure"] = report["structure"]
    state["last_detected_pattern"] = report["patterns"][0]["name"] if report.get("patterns") else ""
    state["last_detected_hint"] = report["patterns"][0].get("hint") if report.get("patterns") else None

    if not allowed:
        state["last_prediction_label"] = None
        state["last_prediction_conf"] = 0
        state["last_prediction_result"] = "TẠM DỪNG"
        state["last_note"] = reason
        state["last_model_predictions"] = {}
        return {"report": report, "adv": adv, "chart_features": chart_features,
                "predictions": {}, "meta": {}, "allowed": False, "reason": reason,
                "relearned": relearned, "resumed": resumed}

    predictions = {"pattern": predict_pattern(labels, report), "structure": predict_structure(labels, report)}
    meta = meta_decision(predictions, state, report, adv)
    state["last_prediction_label"] = meta["final_label"]
    state["last_prediction_conf"] = meta["confidence"]
    state["last_note"] = f"Model: {meta['model']}"
    state["last_structure"] = report["structure"]
    state["last_mode"] = "READY" if len(labels) >= MIN_ANALYSIS_LEN else "NORMAL"
    state["last_model_predictions"] = predictions
    state["last_prediction_result"] = "CHỜ KẾT QUẢ"

    return {"report": report, "adv": adv, "chart_features": chart_features, "predictions": predictions,
            "meta": meta, "allowed": True, "reason": reason, "relearned": relearned, "resumed": resumed}


def build_chart_summary(report: Dict[str, Any], adv: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> str:
    cooldown_text = "ĐANG HỌC LẠI" if state and state.get("cooldown_active") else "BÌNH THƯỜNG"
    return (
        f"Tổng: {report.get('total',0)} | {LOW_LABEL}: {report.get('low',0)} | {HIGH_LABEL}: {report.get('high',0)}\n"
        f"Cấu trúc: {report.get('structure','-')}\n"
        f"Chi tiết: {report.get('detail','-')}\n"
        f"Bệt max: {adv.get('max_streak',0)} | 10 gần: {adv.get('r10_high',0.5)*100:.1f}% {HIGH_LABEL} | "
        f"20 gần: {adv.get('r20_high',0.5)*100:.1f}% {HIGH_LABEL}\n"
        f"Momentum: {adv.get('momentum',0.0):.2f} | Trend: {adv.get('trend_label','TRUNG TÍNH')} ({adv.get('trend',0.0):.2f})\n"
        f"Mượt: {adv.get('smoothness',0.0):.2f} | Đảo chiều: {adv.get('reversal',0.0):.1f}%\n"
        f"Entropy: {report.get('entropy',0.0):.2f} | Volatility: {report.get('volatility',0.0):.2f}\n"
        f"Chế độ: {cooldown_text}"
    )


def _point_color(label: str) -> str:
    return "gold" if label == HIGH_LABEL else "white"


def _point_edge(label: str) -> str:
    return "#3a2b00" if label == HIGH_LABEL else "#444444"


def build_bridge_chart_image(labels: List[str], report: Dict[str, Any], adv: Dict[str, Any], state: Optional[Dict[str, Any]] = None, limit: int = 0) -> Optional[BytesIO]:
    tail = labels[-limit:] if limit and len(labels) > limit else labels[:]
    if not tail:
        return None
    xs = list(range(1, len(tail) + 1))
    ys = [1 if x == HIGH_LABEL else 0 for x in tail]

    fig_w = max(14.0, min(38.0, 0.25 * len(tail) + 10.0))
    fig_h = 7.8 if len(tail) < 120 else 8.4
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=180)
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#11151c")

    for i in range(1, len(xs) + 1):
        ax.axvline(i, color="white", alpha=0.05, linewidth=0.8, zorder=0)
    ax.axhline(0, color="white", alpha=0.05, linewidth=0.8, zorder=0)
    ax.axhline(0.5, color="white", alpha=0.22, linewidth=1.2, linestyle="--", zorder=0)
    ax.axhline(1, color="white", alpha=0.05, linewidth=0.8, zorder=0)
    ax.axhspan(-0.02, 0.5, alpha=0.05, color="#ffffff", zorder=0)
    ax.axhspan(0.5, 1.02, alpha=0.05, color="#ffd700", zorder=0)

    ax.step(xs, ys, where="mid", linewidth=4.5, alpha=0.10, color="white", zorder=2)
    ax.step(xs, ys, where="mid", linewidth=2.8, alpha=0.18, color="#7db7ff", zorder=3)
    ax.step(xs, ys, where="mid", linewidth=2.0, alpha=0.95, color="#cfd8dc", zorder=4)
    ax.scatter(xs, ys, s=180, c=[_point_color(t) for t in tail], edgecolors=[_point_edge(t) for t in tail], linewidths=1.4, zorder=5)
    ax.scatter(xs, ys, s=80, c="none", edgecolors="black", linewidths=0.4, alpha=0.45, zorder=4)

    for x, y, t in zip(xs, ys, tail):
        txt_color = "#111111" if t == HIGH_LABEL else "#222222"
        ax.text(x, y, t, ha="center", va="center", fontsize=9, fontweight="bold", color=txt_color, zorder=6)

    if xs:
        ax.scatter([xs[-1]], [ys[-1]], s=320, c=["#ff4d4d"], edgecolors="white", linewidths=1.8, zorder=7)
        ax.text(xs[-1], ys[-1] + (0.11 if ys[-1] == 1 else -0.11), tail[-1], ha="center", va="center",
                fontsize=11, fontweight="bold", color="white", zorder=8)

    if len(ys) >= 5:
        for w, style, alpha, color in [(5, "--", 0.8, "#7db7ff"), (12, ":", 0.65, "#ffb347")]:
            if len(ys) >= w:
                ma = []
                for i in range(len(ys)):
                    start = max(0, i - w + 1)
                    seg = ys[start:i + 1]
                    ma.append(sum(seg) / len(seg))
                ax.plot(xs, ma, linewidth=1.5 if w == 5 else 1.8, alpha=alpha, linestyle=style, color=color, zorder=4)

    ax.set_ylim(-0.15, 1.15)
    ax.set_yticks([0, 1])
    ax.set_yticklabels([LOW_LABEL, HIGH_LABEL], fontsize=11, color="white")
    ax.set_xlabel("Mẫu gần nhất", fontsize=10, color="white")
    ax.set_ylabel("Trạng thái", fontsize=10, color="white")
    ax.set_title("BIỂU ĐỒ CẦU PHÂN TÍCH - TOÀN BỘ LỊCH SỬ", fontsize=13, fontweight="bold", color="white")

    if len(xs) <= 14:
        ax.set_xticks(xs)
        ax.set_xticklabels([str(i) for i in xs], fontsize=9, color="white")
    else:
        step = max(1, len(xs) // 12)
        ticks = xs[::step]
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(i) for i in ticks], fontsize=9, color="white")

    for spine in ax.spines.values():
        spine.set_color("#6b7280")
        spine.set_alpha(0.35)
    ax.tick_params(colors="white")
    ax.grid(True, axis="y", alpha=0.14, linestyle="-")

    ax.text(0.02, 0.98, build_chart_summary(report, adv, state), transform=ax.transAxes, va="top", ha="left",
            fontsize=9, color="white",
            bbox=dict(boxstyle="round,pad=0.55", facecolor="#121826", alpha=0.92, edgecolor="#44506a"))

    top_patterns = report.get("patterns", [])[:4]
    quick = " / ".join(p.get("name", "") for p in top_patterns) if top_patterns else "TRUNG TÍNH"
    ax.text(0.98, 0.02, f"Cầu: {quick}", transform=ax.transAxes, va="bottom", ha="right", fontsize=9, color="white",
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#1f2937", alpha=0.9, edgecolor="#6b7280"))

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


async def send_bridge_chart(update: Update, labels: List[str], report: Dict[str, Any], adv: Dict[str, Any], title: str, state: Optional[Dict[str, Any]] = None) -> None:
    if not update.message:
        return
    chart = build_bridge_chart_image(labels, report, adv, state=state)
    if chart is None:
        await update.message.reply_text("📉 Chưa đủ dữ liệu để vẽ biểu đồ cầu.")
        return
    try:
        chart.seek(0)
        await update.message.reply_photo(photo=chart, caption=f"{title}\n{build_chart_summary(report, adv, state)}")
    except Exception as e:
        logger.exception("send_bridge_chart failed: %s", e)
        await update.message.reply_text("📉 Không thể gửi biểu đồ lúc này.")


def build_stats_message(report: Dict[str, Any], state: Dict[str, Any], adv: Dict[str, Any]) -> str:
    total = report["total"]
    low_p = safe_div(report["low"] * 100.0, total)
    high_p = safe_div(report["high"] * 100.0, total)

    patterns = report.get("patterns", [])[:4]
    pattern_lines = "\n".join(f"║ • {p['name']}: {p['detail']}" for p in patterns) if patterns else "║ • Chưa có cầu nổi bật"

    model_acc = state.get("model_accuracy", {})
    model_acc_line = f"P:{int(model_acc.get('pattern', 50))}% S:{int(model_acc.get('structure', 50))}%"
    cooldown_line = "ĐANG HỌC LẠI" if state.get("cooldown_active") else "BÌNH THƯỜNG"

    return (
        "╔════════════════════════════╗\n"
        "║      ✅ BẢNG THỐNG KÊ      ║\n"
        "╠════════════════════════════╣\n"
        f"║ Tổng    : {total}\n"
        f"║ {LOW_LABEL:<6}: {report['low']} ({low_p:.1f}%)\n"
        f"║ {HIGH_LABEL:<6}: {report['high']} ({high_p:.1f}%)\n"
        f"║ Cấu trúc: {report['structure']}\n"
        f"║ Chi tiết : {report['detail']}\n"
        f"║ Bệt max  : {adv.get('max_streak', 0)}\n"
        f"║ 10 gần   : {adv.get('r10_high', 0.5) * 100:.1f}% {HIGH_LABEL}\n"
        f"║ 20 gần   : {adv.get('r20_high', 0.5) * 100:.1f}% {HIGH_LABEL}\n"
        f"║ Momentum : {adv.get('momentum', 0.0):.2f}\n"
        f"║ Trend    : {adv.get('trend_label', 'TRUNG TÍNH')} ({adv.get('trend', 0.0):.2f})\n"
        f"║ Mượt     : {adv.get('smoothness', 0.0):.2f}\n"
        f"║ Nhiễu    : {adv.get('noise', 0.0):.2f}\n"
        f"║ Đảo chiều: {adv.get('reversal', 0.0):.1f}%\n"
        f"║ Entropy  : {report.get('entropy', 0.0):.2f}\n"
        f"║ Volatility: {report.get('volatility', 0.0):.2f}\n"
        f"║ Chính xác: {safe_div(state.get('prediction_hits', 0) * 100.0, state.get('prediction_total', 0)):.1f}%\n"
        f"║ Thắng    : {state.get('prediction_hits', 0)}\n"
        f"║ Thua     : {state.get('prediction_misses', 0)}\n"
        f"║ Tổng chốt: {state.get('prediction_total', 0)}\n"
        f"║ Chuỗi thắng max: {state.get('max_correct_streak', 0)}\n"
        f"║ Chuỗi thua  max: {state.get('max_wrong_streak', 0)}\n"
        f"║ M.Acc    : {model_acc_line}\n"
        f"║ Cửa gác  : {state.get('last_gate_status', 'CHỜ')}\n"
        f"║ Lý do    : {state.get('last_gate_reason', 'Chưa kiểm tra')}\n"
        f"║ Học lại  : {cooldown_line}\n"
        f"║ Lý do HL : {state.get('cooldown_reason') or '-'}\n"
        f"║ Ghi chú  : {state.get('last_relearn_note') or state.get('last_resume_note') or '-'}\n"
        f"║ Cầu hiện tại: {state.get('last_detected_pattern') or '-'}\n"
        f"║ Hướng    : {state.get('last_detected_hint') or '-'}\n"
        f"{pattern_lines}\n"
        "╚════════════════════════════╝"
    )


def build_analysis_message(report: Dict[str, Any], adv: Dict[str, Any], meta: Dict[str, Any], predictions: Dict[str, Dict[str, Any]]) -> str:
    warning = ""
    if adv.get("noise", 0.0) > 0.70:
        warning = "⚠️ Cầu nhiễu cao - nên thận trọng"
    elif adv.get("reversal", 0.0) > 25:
        warning = "⚠️ Có khả năng đảo chiều mạnh"

    top_patterns = report.get("patterns", [])[:4]
    pattern_text = " / ".join([p["name"] for p in top_patterns]) if top_patterns else "TRUNG TÍNH"
    chart_read = f"Tổng {report.get('total', 0)} | {LOW_LABEL} {report.get('low', 0)} | {HIGH_LABEL} {report.get('high', 0)} | Cấu trúc {report.get('structure', '-')}"

    return (
        "╔════════════════════════════╗\n"
        "║       🔍 PHÂN TÍCH CẦU     ║\n"
        "╠════════════════════════════╣\n"
        f"║ Nhìn chart: {chart_read}\n"
        f"║ Cầu chính : {pattern_text}\n"
        f"║ Detail    : {report.get('detail', '-')}\n"
        f"║ 10/20     : {adv.get('r10_high', 0.5) * 100:.1f}% / {adv.get('r20_high', 0.5) * 100:.1f}% {HIGH_LABEL}\n"
        f"║ Momentum  : {adv.get('momentum', 0.0):.2f}\n"
        f"║ Trend     : {adv.get('trend_label', 'TRUNG TÍNH')} ({adv.get('trend', 0.0):.2f})\n"
        f"║ Mượt      : {adv.get('smoothness', 0.0):.2f}\n"
        f"║ Nhiễu     : {adv.get('noise', 0.0):.2f}\n"
        f"║ Đảo chiều : {adv.get('reversal', 0.0):.1f}%\n"
        f"║ Pattern   : {predictions.get('pattern', {}).get('label', '-')} ({predictions.get('pattern', {}).get('confidence', 0)}%)\n"
        f"║ Struct    : {predictions.get('structure', {}).get('label', '-')} ({predictions.get('structure', {}).get('confidence', 0)}%)\n"
        f"║ Kết luận  : {meta.get('final_label', '-')}\n"
        f"║ Model     : {meta.get('model', '-')}\n"
        f"║ Tỷ lệ     : {meta.get('confidence', 0)}%\n"
        f"{warning}\n"
        "╚════════════════════════════╝"
    )


def build_final_message(meta: Dict[str, Any], state: Dict[str, Any]) -> str:
    return (
        f"CHỐT GỐC: {meta.get('final_label', '-')}\n"
        f"MODEL   : {meta.get('model', '-')}\n"
        f"TỶ LỆ   : {meta.get('confidence', 0)}%\n"
        f"THẮNG   : {state.get('prediction_hits', 0)}\n"
        f"THUA    : {state.get('prediction_misses', 0)}\n"
        f"TỔNG CHỐT: {state.get('prediction_total', 0)}\n"
        f"CHUỖI THẮNG MAX: {state.get('max_correct_streak', 0)}\n"
        f"CHUỖI THUA  MAX: {state.get('max_wrong_streak', 0)}\n"
    )


def build_stop_message(reason: str, report: Dict[str, Any], state: Dict[str, Any]) -> str:
    return (
        "╔════════════════════════════╗\n"
        "║        ⏸ BOT TẠM DỪNG     ║\n"
        "╠════════════════════════════╣\n"
        f"║ Lý do   : {reason}\n"
        f"║ Cấu trúc: {report.get('structure', '-')}\n"
        f"║ Chi tiết : {report.get('detail', '-')}\n"
        f"║ Tổng    : {report.get('total', 0)}\n"
        f"║ Trạng thái: {'Đang học lại' if state.get('cooldown_active') else 'Bình thường'}\n"
        "╚════════════════════════════╝"
    )


def build_relearn_message(report: Dict[str, Any], adv: Dict[str, Any], state: Dict[str, Any]) -> str:
    return (
        "╔════════════════════════════╗\n"
        "║      🧠 TỰ HỌC LẠI         ║\n"
        "╠════════════════════════════╣\n"
        f"║ Chuỗi thua: {LOSS_STREAK_LIMIT}\n"
        f"║ Đã reset logic/model: Có\n"
        f"║ Tổng lịch sử: {report.get('total', 0)}\n"
        f"║ Cấu trúc   : {report.get('structure', '-')}\n"
        f"║ Chi tiết   : {report.get('detail', '-')}\n"
        f"║ Mượt       : {adv.get('smoothness', 0.0):.2f}\n"
        f"║ Nhiễu      : {report.get('volatility', 0.0):.2f}\n"
        f"║ Snapshot   : {state.get('last_relearn_snapshot') or '-'}\n"
        "╚════════════════════════════╝"
    )


def build_resume_message(state: Dict[str, Any]) -> str:
    return (
        "╔════════════════════════════╗\n"
        "║       ✅ MỞ LẠI CẦU        ║\n"
        "╠════════════════════════════╣\n"
        f"║ Trạng thái: {state.get('last_resume_note') or 'Đã hồi phục'}\n"
        f"║ Chuỗi thua: {state.get('current_wrong_streak', 0)}\n"
        f"║ Học lại   : {'TẮT' if not state.get('cooldown_active') else 'ĐANG BẬT'}\n"
        "╚════════════════════════════╝"
    )


def build_stage_message(step: int) -> str:
    return "✅ Bước 1: Đã cập nhật bảng thống kê." if step == 1 else "🔍 Bước 2: Đã phân tích cầu." if step == 2 else "🧠 Bước 3: Hoàn tất."


async def send_robot_status(update: Update, caption: str) -> Optional[Any]:
    if not update.message:
        return None
    ensure_robot_asset()
    try:
        with open(ROBOT_IMAGE_PATH, "rb") as f:
            return await update.message.reply_photo(photo=f, caption=caption)
    except Exception as e:
        logger.exception("send_robot_status failed: %s", e)
        await update.message.reply_text(caption)
        return None


async def send_robot_analysis_sequence(update: Update, meta: Dict[str, Any], state: Dict[str, Any]) -> None:
    msg = await send_robot_status(
        update,
        "🤖 ĐANG PHÂN TÍCH...\n⏳ Vui lòng chờ 5 giây để robot xác nhận cầu mới."
    )
    await asyncio.sleep(ROBOT_ANALYZE_DELAY)

    if msg:
        try:
            await msg.edit_caption(
                caption=(
                    f"✅ ĐÃ PHÂN TÍCH XONG\n"
                    f"🤖 Robot đã sẵn sàng\n"
                    f"Chốt: {meta.get('final_label', '-')}\n"
                    f"Tỷ lệ: {meta.get('confidence', 0)}%"
                )
            )
        except Exception as e:
            logger.exception("edit_caption failed: %s", e)

    # hiện thêm 1 tin nhắn robot để thấy “chung với robot” rõ hơn
    try:
        await update.message.reply_text(
            "🤖 ROBOT XÁC NHẬN XONG\n"
            f"Chốt: {meta.get('final_label', '-')}\n"
            f"Tỷ lệ: {meta.get('confidence', 0)}%\n"
            f"Trạng thái: {state.get('last_gate_status', 'CHỜ')}"
        )
    except Exception:
        pass


async def process_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, nums: Optional[List[int]] = None) -> None:
    if not update.message:
        return

    chat_id = get_key(update)

    async with STATE_LOCK:
        state = repair_state(await load_state(chat_id))
        entries: List[Tuple[int, str]] = []

        if nums:
            for n in nums:
                entries.append((n, map_value(n)))

        if entries:
            await append_history(chat_id, entries)

        rows = await load_history_rows(chat_id, limit=HISTORY_ANALYSIS_LIMIT)
        full_values = [r[0] for r in rows]
        full_labels = [r[1] for r in rows]

        state["values"] = _safe_tail(full_values, RECENT_CACHE)
        state["labels"] = _safe_tail(full_labels, RECENT_CACHE)
        rebuild_counters_from_labels(state, full_labels)

        if entries:
            latest_actual = entries[-1][1]
            update_prediction_feedback(state, latest_actual)
            prev_predictions = state.get("last_model_predictions", {})
            if isinstance(prev_predictions, dict) and prev_predictions:
                update_model_accuracy(state, prev_predictions, latest_actual)
            clear_loss_cooldown(state)

        result = analyze_state_from_labels(state, full_labels)
        await save_state(chat_id, state)
        users[chat_id] = state
        trim_cache()

    report = result["report"]
    adv = result["adv"]

    await update.message.reply_text(build_stage_message(1))
    await send_bridge_chart(update, full_labels, report, adv, "📈 BIỂU ĐỒ CẦU - CẬP NHẬT MỚI", state)
    await update.message.reply_text(build_stats_message(report, state, adv))

    if result.get("relearned", False):
        await update.message.reply_text(build_relearn_message(report, adv, state))
    if result.get("resumed", False):
        await update.message.reply_text(build_resume_message(state))

    if not result.get("allowed", False):
        await update.message.reply_text(build_stop_message(result.get("reason", "Cầu chưa rõ"), report, state))
        return

    meta = result["meta"]
    predictions = result["predictions"]

    await update.message.reply_text(build_stage_message(2))

    # Robot hiện trước, đợi 5 giây rồi mới trả kết quả
    await send_robot_analysis_sequence(update, meta, state)

    await send_bridge_chart(update, full_labels, report, adv, "📈 BIỂU ĐỒ CẦU - PHÂN TÍCH", state)
    await update.message.reply_text(build_analysis_message(report, adv, meta, predictions))
    await update.message.reply_text(build_final_message(meta, state))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📘 TRỢ GIÚP\n"
        f"/stats - xem bảng thống kê\n"
        f"/ai - phân tích cầu\n"
        f"/next - giống /ai\n"
        f"/reset - xóa dữ liệu chat hiện tại\n"
        f"/factory_reset - xóa sạch toàn bộ bot\n\n"
        f"Quy đổi: số >= {THRESHOLD} -> {HIGH_LABEL}, số < {THRESHOLD} -> {LOW_LABEL}.\n"
        f"Khi thua {LOSS_STREAK_LIMIT} liên tiếp, bot sẽ tạm dừng, tự reset logic và học lại từ đầu lịch sử.\n"
        f"Luồng hoạt động: cập nhật thống kê → biểu đồ cầu → robot phân tích → kết quả chốt."
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = get_key(update)
    state = repair_state(await load_state(chat_id, force_reload=True))
    rows = await load_history_rows(chat_id, limit=HISTORY_ANALYSIS_LIMIT)
    labels = [r[1] for r in rows]
    state["labels"] = _safe_tail(labels, RECENT_CACHE)
    rebuild_counters_from_labels(state, labels)
    report = build_report(labels)
    adv = advanced_metrics(labels)
    adv.update(extract_chart_features(labels))
    await send_bridge_chart(update, labels, report, adv, "📈 BIỂU ĐỒ CẦU - THỐNG KÊ MỚI NHẤT", state)
    await update.message.reply_text(build_stats_message(report, state, adv))


async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = get_key(update)

    async with STATE_LOCK:
        state = repair_state(await load_state(chat_id, force_reload=True))
        rows = await load_history_rows(chat_id, limit=HISTORY_ANALYSIS_LIMIT)
        labels = [r[1] for r in rows]
        state["labels"] = _safe_tail(labels, RECENT_CACHE)
        rebuild_counters_from_labels(state, labels)
        clear_loss_cooldown(state)
        result = analyze_state_from_labels(state, labels)
        await save_state(chat_id, state)
        users[chat_id] = state
        trim_cache()

    report = result["report"]
    adv = result["adv"]

    await update.message.reply_text(build_stage_message(1))
    await send_bridge_chart(update, labels, report, adv, "📈 BIỂU ĐỒ CẦU - DÙNG CHO PHÂN TÍCH", state)
    await update.message.reply_text(build_stats_message(report, state, adv))

    if result.get("relearned", False):
        await update.message.reply_text(build_relearn_message(report, adv, state))
    if result.get("resumed", False):
        await update.message.reply_text(build_resume_message(state))

    if not result.get("allowed", False):
        await update.message.reply_text(build_stop_message(result.get("reason", "Cầu chưa rõ"), report, state))
        return

    meta = result["meta"]
    predictions = result["predictions"]

    await update.message.reply_text(build_stage_message(2))
    await send_robot_analysis_sequence(update, meta, state)
    await update.message.reply_text(build_analysis_message(report, adv, meta, predictions))
    await update.message.reply_text(build_final_message(meta, state))


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ai_cmd(update, context)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = get_key(update)

    def _work():
        with db_connect() as conn:
            conn.execute("DELETE FROM history WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM chat_state WHERE chat_id = ?", (chat_id,))
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)

    users.pop(chat_id, None)
    await update.message.reply_text("🔄 Đã reset chat hiện tại.")


async def factory_reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    def _work():
        with db_connect() as conn:
            conn.execute("DELETE FROM history")
            conn.execute("DELETE FROM chat_state")
            conn.commit()

    async with DB_LOCK:
        await run_db_work(_work)

    users.clear()
    await update.message.reply_text("🧼 Đã xóa sạch toàn bộ dữ liệu.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        nums = parse_input(update.message.text)
        if not nums:
            return
        await process_chat(update, context, nums)
    except Exception as e:
        logger.exception("handle_text failed: %s", e)
        if update.message:
            await update.message.reply_text("❌ Lỗi khi xử lý dữ liệu")


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Global error: %s", context.error)
    err = context.error
    if isinstance(err, RetryAfter):
        await asyncio.sleep(err.retry_after + 1)
    elif isinstance(err, (TimedOut, NetworkError, TelegramError)):
        await asyncio.sleep(1.0)
    try:
        if getattr(update, "message", None):
            await update.message.reply_text("⚠️ Có lỗi tạm thời, bot đã tự giữ an toàn.")
    except Exception:
        pass


def main():
    init_db()
    ensure_robot_asset()
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(False).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("ai", ai_cmd))
    app.add_handler(CommandHandler("next", next_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("factory_reset", factory_reset_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🔥 BOT THỐNG KÊ - PHÂN TÍCH CẦU ĐANG CHẠY...")
    app.run_polling(drop_pending_updates=True)


def run_bot_forever():
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.exception("Bot crashed, restarting in 5s: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    run_bot_forever()
