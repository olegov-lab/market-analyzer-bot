import re as _re

from aiogram.filters import Command
from aiogram.types import Message

from bot.state import bot, db, dp, redis_client, _greeting_for, _ts_for, _menu_kb, set_user_lang, get_user_lang
from bot.i18n import t
from btcbot.news import fetch_news
from btcbot.subscription import activate_trial
from btcbot.game import GameEngine

game = GameEngine(db)


@dp.message(Command(commands=["start"]))
async def start(message: Message):
    uid = message.from_user.id
    await db.upsert_user(uid, message.from_user.username)
    await set_user_lang(uid, message.from_user.language_code or "en")
    lang = await get_user_lang(uid)

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
        await message.answer(t("🎉 *BTC Monitor*\n\nВы пришли по реферальной ссылке! За вашим пригласившим закреплён бонус.", lang), parse_mode="Markdown")

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
        f"{await _greeting_for(uid, message.from_user.first_name, lang)} 🤖\n\n"
        f"{t('Я *BTC Monitor* — твой AI-аналитик Bitcoin.', lang)}"
        f"{news_part}\n\n"
        f"{t('🎁 *3 дня PRO* — бесплатно! ∞ AI-вопросов, продвинутые алерты.', lang)}\n\n"
        f"{t('📊 Кнопка `📊 BTC` слева от ввода → Mini App', lang)}\n\n"
        f"{t('💰 `/btc` — цена и индикаторы', lang)}\n"
        f"{t('🔮 `/predict` — прогноз', lang)}\n"
        f"{t('🧠 `/ask` — AI-консультант', lang)}\n"
        f"{t('🎮 `/portfolio` — портфель и игры', lang)}\n"
        f"{t('📰 `/news` — пульс рынка', lang)}\n"
        f"{t('📖 `/learn` — азбука крипты', lang)}\n"
        f"{t('🔔 `/subscribe` — уведомления', lang)}\n"
        f"{t('🌍 `/timezone` — часовой пояс', lang)}\n"
        f"{t('📋 `/alerts` — мои подписки / отписка', lang)}\n"
        f"{t('👥 `/referral` — привести друга (+5⭐)', lang)}\n"
        f"{t('☕ `/donate` — поддержать проект', lang)}\n"
        f"{t('❓ `/help` — всё остальное', lang)}",
        parse_mode="Markdown",
        reply_markup=_menu_kb(lang),
    )


@dp.message(Command(commands=["referral"]))
async def referral_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    info = await game.get_referral_info(uid)
    ref_link = info["ref_link"]
    count = info["referrals"]
    await message.answer(
        f"{t('👥 *BTC Monitor* · Рефералы', lang)}\n\n"
        f"{t('Приведи друга и получи **+5⭐** (бонус для майнинга), а твой друг — **+10% к майнингу** за каждый реферал.', lang)}\n\n"
        f"{t('👤 Твои рефералы: **{count}**', lang, count=count)}\n"
        f"{t('🔗 Твоя ссылка:', lang)}\n`{ref_link}`\n\n"
        f"{t('Просто отправь другу эту ссылку — он перейдёт в бота, и бонус закрепится автоматически.', lang)}",
        parse_mode="Markdown",
        reply_markup=_menu_kb(lang),
    )
