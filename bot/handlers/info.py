import re as _re

from aiogram.filters import Command
from aiogram.types import Message

from bot.state import bot, db, dp, menu_kb, redis_client, _greeting_for, _ts_for
from btcbot.news import fetch_news
from btcbot.subscription import activate_trial
from btcbot.game import GameEngine

game = GameEngine(db)


@dp.message(Command(commands=["start"]))
async def start(message: Message):
    uid = message.from_user.id
    await db.upsert_user(uid, message.from_user.username)

    # Process referral deep link: start=ref_123456
    ref_id = None
    if message.text and "ref_" in message.text:
        try:
            ref_str = message.text.split("ref_")[-1].split()[0]
            ref_id = int(ref_str)
        except (ValueError, IndexError):
            pass

    if ref_id and ref_id != uid:
        await game.add_referral(ref_id, uid)
        await message.answer("🎉 *BTC Monitor*\n\nВы пришли по реферальной ссылке! За вашим пригласившим закреплён бонус.", parse_mode="Markdown")

    await activate_trial(db, uid)
    articles = await fetch_news(redis_client)
    news_part = ""
    if articles:
        sent_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
        news_lines = []
        for a in articles[:3]:
            emoji = sent_emoji.get(a.get("sentiment", ""), "🟡")
            clean = _re.sub(r'<[^>]+>', '', a['title'])
            clean = clean.replace('[', '').replace(']', '')
            href = a.get("url", "")
            if href:
                news_lines.append(f"{emoji} [{clean}]({href})")
            else:
                news_lines.append(f"{emoji} {clean}")
        news_part = "\n\n📰 *Последние новости:*\n" + "\n".join(news_lines)
    await message.answer(
        f"{await _greeting_for(uid, message.from_user.first_name)} 🤖\n\n"
        "Я *BTC Monitor* — твой AI-аналитик Bitcoin."
        f"{news_part}\n\n"
        "🎁 *3 дня PRO* — бесплатно! ∞ AI-вопросов, продвинутые алерты.\n\n"
        "📊 Кнопка `📊 BTC` слева от ввода → Mini App\n\n"
        "💰 `/btc` — цена и индикаторы\n"
        "🔮 `/predict` — прогноз\n"
        "🧠 `/ask` — AI-консультант\n"
        "🎮 `/portfolio` — портфель и игры\n"
        "📰 `/news` — пульс рынка\n"
        "📖 `/learn` — азбука крипты\n"
        "🔔 `/subscribe` — уведомления\n"
        "🌍 `/timezone` — часовой пояс\n"
        "📋 `/alerts` — мои подписки / отписка\n"
        "👥 `/referral` — привести друга (+5⭐)\n"
        "☕ `/donate` — поддержать проект\n"
        "❓ `/help` — всё остальное",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )


@dp.message(Command(commands=["referral"]))
async def referral_cmd(message: Message):
    uid = message.from_user.id
    info = await game.get_referral_info(uid)
    ref_link = info["ref_link"]
    count = info["referrals"]
    await message.answer(
        "👥 *BTC Monitor* · Рефералы\n\n"
        "Приведи друга и получи **+5⭐** (бонус для майнинга), "
        "а твой друг — **+10% к майнингу** за каждый реферал.\n\n"
        f"👤 Твои рефералы: **{info['count']}**\n"
        f"🔗 Твоя ссылка:\n`{ref_link}`\n\n"
        "Просто отправь другу эту ссылку — он перейдёт в бота, "
        "и бонус закрепится автоматически.",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )
