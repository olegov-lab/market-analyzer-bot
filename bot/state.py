from datetime import datetime, timezone

import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database
from btcbot.fear_greed import FearGreedIndex

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
db = Database(settings.database_url)
redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
analyzer = Analyzer(db, redis_client)
fear_greed = FearGreedIndex(redis_client)

menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/btc"), KeyboardButton(text="/predict")],
        [KeyboardButton(text="/subscribe"), KeyboardButton(text="/alerts")],
        [KeyboardButton(text="/news"), KeyboardButton(text="/learn")],
        [KeyboardButton(text="/help")],
    ],
    resize_keyboard=True,
)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("🕐 %-d %B %Y, %H:%M UTC")


def _rsi_bar(rsi: float) -> str:
    bar_len = 10
    filled = max(0, min(bar_len, int(rsi / 100 * bar_len)))
    bar = "▓" * filled + "░" * (bar_len - filled)
    color = "🟢" if rsi < 40 else "🟡" if rsi < 60 else "🔴"
    return f"{color} {bar} {rsi:.1f}"


def _greeting(name: str = "") -> str:
    h = datetime.now(timezone.utc).hour
    base = "Доброе утро" if 5 <= h < 12 else "Добрый день" if 12 <= h < 18 else "Добрый вечер" if 18 <= h < 23 else "Доброй ночи"
    return f"{base}, {name}!" if name else f"{base}!"
