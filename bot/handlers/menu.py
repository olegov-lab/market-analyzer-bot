from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.state import dp


@dp.message(lambda m: m.text == "❓ Ещё" or m.text == "/help")
async def menu_help(message: Message):
    await message.answer(
        "❓ *BTC Monitor* · Помощь\n\n"
        "📊 **Mini App** — кнопка `📊 BTC` слева от ввода\n\n"
        "💰 `/btc` — цена и индикаторы\n"
        "🔮 `/predict` — прогноз\n"
        "🧠 `/ask` — AI-аналитик\n"
        "🎮 `/portfolio` — симулятор\n"
        "📰 `/news` — новости\n"
        "📖 `/learn` — азбука\n"
        "🔔 `/subscribe` — уведомления\n"
        "🏆 `/leaderboard` — топ трейдеров\n"
        "👥 `/referral` — привести друга (+5⭐)\n"
        "🌍 `/timezone` — часовой пояс\n"
        "☕ `/donate` — поддержать проект\n\n"
        "♻️ Данные: Binance · Прогноз: 1ч / 6ч",
        parse_mode="Markdown",
    )
