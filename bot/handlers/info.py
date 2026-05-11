from aiogram.filters import Command
from aiogram.types import Message

from bot.state import bot, db, dp, menu_kb, redis_client, _greeting, _ts
from btcbot.news import fetch_news


@dp.message(Command(commands=["start"]))
async def start(message: Message):
    await db.upsert_user(message.from_user.id, message.from_user.username)
    # 3-day free PRO trial
    trial_key = f"trial:{message.from_user.id}"
    await redis_client.setex(trial_key, 259200, "1")  # 72 hours
    articles = await fetch_news(redis_client)
    news_part = ""
    if articles:
        sent_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
        news_lines = []
        for a in articles[:3]:
            emoji = sent_emoji.get(a.get("sentiment", ""), "🟡")
            news_lines.append(f"{emoji} {a['title']}")
        news_part = "\n\n📰 *Последние новости:*\n" + "\n".join(news_lines)
    await message.answer(
        f"{_greeting(message.from_user.first_name)} 🤖\n\n"
        "Я *BTC Monitor* — твой AI-аналитик Bitcoin с 25 агентами."
        f"{news_part}\n\n"
        "🎁 *3 дня PRO* — бесплатно! ∞ AI-вопросов, продвинутые алерты.\n\n"
        "📊 Кнопка `📊 BTC` слева от ввода → Mini App\n\n"
        "💰 `/btc` — аналитика\n"
        "🧠 `/ask` — AI-консультант\n"
        "🎮 `/portfolio` — симулятор\n"
        "📰 `/news` — пульс рынка\n"
        "❓ `/help` — всё остальное",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )
