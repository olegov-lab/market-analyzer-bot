from aiogram.filters import Command
from aiogram.types import Message

from bot.state import dp, menu_kb, redis_client, _ts
from btcbot.news import build_market_brain_comment, fetch_news


@dp.message(Command(commands=["news"]))
async def news_cmd(message: Message):
    articles = await fetch_news(redis_client)
    if not articles:
        await message.answer("Новостей пока нет", reply_markup=menu_kb)
        return

    bull_count = sum(1 for a in articles if a.get("sentiment") == "bullish")
    bear_count = sum(1 for a in articles if a.get("sentiment") == "bearish")
    total = len(articles)

    mood = "🟢 бычье" if bull_count > bear_count else "🔴 медвежье" if bear_count > bull_count else "🟡 нейтральное"

    worry = bear_count / total if total else 0
    worry_label = "🔴 высокий" if worry >= 0.6 else "🟡 средний" if worry >= 0.3 else "🟢 низкий"

    lines = ["📊 *BTC Monitor* · Пульс", "", _ts(), ""]
    lines.append(f"▸ **Настроение:** {mood}")
    lines.append(f"▸ **Бычьих:** {bull_count}  **Медвежьих:** {bear_count}")
    lines.append(f"▸ **Тревога:** {worry_label}")
    lines.append("")

    emoji_map = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
    for a in articles:
        sentiment = a.get("sentiment", "neutral")
        emoji = emoji_map.get(sentiment, "🟡")
        src = a.get("source", "")
        src_part = f" — {src}" if src else ""
        lines.append(f"{emoji} [{a['title']}]({a['url']}){src_part}")

    lines.append("")
    lines.append(f"💬 **Аналитик рынка:** {build_market_brain_comment(bull_count, bear_count, total)}")
    lines.append("")
    lines.append("♻️ Обновление: новости — 5 мин")

    await message.answer("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=menu_kb)
