from aiogram.filters import Command
from aiogram.types import Message

from bot.state import bot, db, dp, menu_kb, redis_client, _greeting, _ts
from btcbot.news import fetch_news


@dp.message(Command(commands=["start"]))
async def start(message: Message):
    await db.upsert_user(message.from_user.id, message.from_user.username)
    articles = await fetch_news(redis_client)
    news_part = ""
    if articles:
        sent_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
        news_lines = []
        for a in articles[:3]:
            emoji = sent_emoji.get(a.get("sentiment", ""), "🟡")
            news_lines.append(f"{emoji} {a['title']}")
        news_part = "\n\n📰 *Последние новости:*\n" + "\n".join(news_lines) + "\n\n── Новости ──\n📢 `/news` — все новости"
    await message.answer(
        f"{_greeting(message.from_user.first_name)} 🤖\n\n"
        "Я *BTC Monitor* — слежу за биткоином и помогаю понять, что происходит с ценой."
        f"{news_part}\n\n"
        "📊 Кнопка слева от ввода — Mini App с полной аналитикой\n\n"
        "💰 `/btc` — цена и индикаторы\n"
        "🔮 `/predict` — прогноз\n"
        "📖 `/learn` — азбука крипты\n"
        "📢 `/subscribe` — уведомления\n"
        "📰 `/news` — новости\n"
        "❌ `/alerts` — управление подписками\n"
        "❓ `/help` — помощь",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )


@dp.message(Command(commands=["help"]))
async def help_cmd(message: Message):
    await message.answer(
        "🤖 *BTC Monitor* · Помощь\n\n"
        "📊 **Mini App** — кнопка слева от ввода (`📊 BTC`)\n\n"
        "💰 `/btc` — цена и индикаторы\n"
        "🔮 `/predict` — прогноз\n"
        "📖 `/learn` — азбука крипты\n"
        "📢 `/subscribe` — подписка на уведомления\n"
        "❌ `/alerts` — управление подписками\n"
        "📰 `/news` — новости Bitcoin\n\n"
        "♻️ Данные: Binance · Прогноз: 1ч / 6ч",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )
