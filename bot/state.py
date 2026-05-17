from datetime import datetime
import zoneinfo

import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database
from btcbot.fear_greed import FearGreedIndex
from bot.i18n import t, user_lang_key

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
db = Database(settings.database_url, pool_min_size=settings.db_pool_min, pool_max_size=settings.db_pool_max)
redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
analyzer = Analyzer(db, redis_client)
fear_greed = FearGreedIndex(redis_client)

async def get_user_lang(user_id: int) -> str:
    lang = await redis_client.get(user_lang_key(user_id))
    return lang or "ru"

async def set_user_lang(user_id: int, lang: str) -> None:
    code = "ru" if lang.startswith("ru") else "en"
    await redis_client.setex(user_lang_key(user_id), 86400 * 365, code)

def _menu_kb(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("🧠 AI Чат", lang)), KeyboardButton(text=t("📊 Аналитика", lang))],
            [KeyboardButton(text=t("🎮 Трейдинг", lang)), KeyboardButton(text=t("📰 Новости", lang))],
            [KeyboardButton(text=t("❓ Ещё", lang))],
        ],
        resize_keyboard=True,
    )

menu_kb = _menu_kb()

HELP_KEYBOARD = {"btc": "📊 Аналитика", "ask": "🧠 AI Чат", "portfolio": "🎮 Трейдинг", "news": "📰 Новости", "help": "❓ Ещё"}

def help_kb(lang: str = "ru"):
    return {k: t(v, lang) for k, v in HELP_KEYBOARD.items()}


def _ts() -> str:
    now = datetime.now()
    d = now.day
    month = now.strftime("%B")
    return f"🕐 {d} {month} {now.year}, {now.strftime('%H:%M')}"


_ts_tz_cache: dict[int, str] = {}
_MAX_TZ_CACHE = 1000

async def _tz_for(user_id: int) -> zoneinfo.ZoneInfo:
    if user_id not in _ts_tz_cache and len(_ts_tz_cache) >= _MAX_TZ_CACHE:
        _ts_tz_cache.clear()
    tz_name = _ts_tz_cache.get(user_id) or await db.get_user_timezone(user_id)
    _ts_tz_cache[user_id] = tz_name
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return zoneinfo.ZoneInfo("Europe/Moscow")

def _ts_from_tz(tz: zoneinfo.ZoneInfo) -> str:
    now = datetime.now(tz)
    return f"🕐 {now.day} {now.strftime('%B')} {now.year}, {now.strftime('%H:%M')}"

async def _ts_for(user_id: int) -> str:
    return _ts_from_tz(await _tz_for(user_id))


def _clear_tz_cache(user_id: int) -> None:
    _ts_tz_cache.pop(user_id, None)


def _greeting(name: str = "", lang: str = "ru") -> str:
    h = datetime.now().hour
    base = "Доброе утро" if 5 <= h < 12 else "Добрый день" if 12 <= h < 18 else "Добрый вечер" if 18 <= h < 23 else "Доброй ночи"
    base = t(base, lang)
    return f"{base}, {name}!" if name else f"{base}!"


def _rsi_bar(rsi: float) -> str:
    bar_len = 10
    filled = max(0, min(bar_len, int(rsi / 100 * bar_len)))
    bar = "▓" * filled + "░" * (bar_len - filled)
    color = "🟢" if rsi < 40 else "🟡" if rsi < 60 else "🔴"
    return f"{color} {bar} {rsi:.1f}"


async def _greeting_for(user_id: int, name: str = "", lang: str = "ru") -> str:
    if user_id not in _ts_tz_cache and len(_ts_tz_cache) >= _MAX_TZ_CACHE:
        _ts_tz_cache.clear()
    tz_name = _ts_tz_cache.get(user_id) or await db.get_user_timezone(user_id)
    _ts_tz_cache[user_id] = tz_name
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
    h = datetime.now(tz).hour
    base = "Доброе утро" if 5 <= h < 12 else "Добрый день" if 12 <= h < 18 else "Добрый вечер" if 18 <= h < 23 else "Доброй ночи"
    base = t(base, lang)
    return f"{base}, {name}!" if name else f"{base}!"
