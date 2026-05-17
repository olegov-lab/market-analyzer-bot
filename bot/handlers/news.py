from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import Message

from bot.state import dp, redis_client, _tz_for, _ts_from_tz, get_user_lang, _menu_kb
from bot.i18n import t
from btcbot.news import build_market_brain_comment, fetch_news


@dp.message(or_f(Command(commands=["news"]), F.text == "📰 Новости"))
async def news_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    articles = await fetch_news(redis_client)
    if not articles:
        await message.answer(t("Новостей пока нет", lang), reply_markup=_menu_kb(lang))
        return

    bull_count = sum(1 for a in articles if a.get("sentiment") == "bullish")
    bear_count = sum(1 for a in articles if a.get("sentiment") == "bearish")
    total = len(articles)

    mood = t("🟢 бычье", lang) if bull_count > bear_count else t("🔴 медвежье", lang) if bear_count > bull_count else t("🟡 нейтральное", lang)

    worry = bear_count / total if total else 0
    worry_label = t("🔴 высокий", lang) if worry >= 0.6 else t("🟡 средний", lang) if worry >= 0.3 else t("🟢 низкий", lang)

    lines = ["📊 *BTC Monitor* · Market Pulse", "", ts, ""]
    lines.append(t("▸ **Настроение:** {mood}", lang, mood=mood))
    lines.append(t("▸ **Бычьих:** {bull}  **Медвежьих:** {bear}", lang, bull=bull_count, bear=bear_count))
    lines.append(t("▸ **Тревога:** {worry}", lang, worry=worry_label))
    lines.append("")

    emoji_map = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
    for a in articles:
        sentiment = a.get("sentiment", "neutral")
        emoji = emoji_map.get(sentiment, "🟡")
        src = a.get("source", "")
        src_part = f" — {src}" if src else ""
        lines.append(f"{emoji} [{a['title']}]({a['url']}){src_part}")

    lines.append("")
    lines.append(t("💬 **Аналитик рынка:** {comment}", lang, comment=build_market_brain_comment(bull_count, bear_count, total)))
    lines.append("")
    lines.append(t("♻️ Обновление: новости — 5 мин", lang))

    await message.answer("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=_menu_kb(lang))
