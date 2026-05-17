from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice, ContentType

from bot.state import bot, db, dp, _menu_kb, get_user_lang
from bot.i18n import t
from btcbot.subscription import activate_pro, activate_pro_plus, get_user_tier, Tier
from loguru import logger


@dp.message(F.web_app_data)
async def web_app_data(message: Message):
    import json
    lang = await get_user_lang(message.from_user.id)
    logger.info(f"web_app_data received from {message.from_user.id}")
    try:
        raw = message.web_app_data.data if message.web_app_data else ""
        logger.info(f"web_app_data raw: {raw}")
        data = json.loads(raw)
        action = data.get("action", "")
        logger.info(f"web_app_data action={action}, tier={data.get('tier')}")
        if action != "subscribe":
            return
        tier = data.get("tier", "pro")
    except Exception as e:
        logger.error(f"web_app_data parse error: {e}")
        return

    user_tier = await get_user_tier(db, message.from_user.id)
    if tier == "pro" and user_tier in (Tier.PRO, Tier.PRO_PLUS):
        await message.answer(t("💎 У вас уже активна подписка PRO.", lang), reply_markup=_menu_kb(lang))
        return
    if tier == "pro_plus" and user_tier == Tier.PRO_PLUS:
        await message.answer(t("💎 У вас уже активна подписка PRO+.", lang), reply_markup=_menu_kb(lang))
        return

    if tier == "pro":
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="BTC Monitor PRO",
            description=t("Безлимитный AI-чат, продвинутые алерты, безлимит сделок", lang),
            payload="pro_monthly",
            currency="XTR",
            prices=[LabeledPrice(label="PRO на 1 месяц", amount=80)],
            provider_token="",
        )
    elif tier == "pro_plus":
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="BTC Monitor PRO+",
            description=t("Всё из PRO + голос, confidence score ML, персональный дашборд", lang),
            payload="pro_plus_monthly",
            currency="XTR",
            prices=[LabeledPrice(label="PRO+ на 1 месяц", amount=200)],
            provider_token="",
        )
    await message.answer(t("💎 Счёт выставлен в чате выше. Оплатите Telegram Stars для активации.", lang), reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["upgrade"]))
async def upgrade(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tier = await get_user_tier(db, uid)
    if tier in (Tier.PRO, Tier.PRO_PLUS):
        await message.answer(
            f"{t('💎 *BTC Monitor* · Подписка', lang)}\n\n{t('У вас уже активна подписка {tier}.', lang, tier=tier.value.upper())}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return
    await message.answer(
        f"{t('💎 *BTC Monitor* · Подписка', lang)}\n\n{t('Выберите тариф:', lang)}",
        parse_mode="Markdown",
        reply_markup=_menu_kb(lang),
    )
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="BTC Monitor PRO",
        description=t("Безлимитный AI-чат, продвинутые алерты, безлимит сделок", lang),
        payload="pro_monthly",
        currency="XTR",
        prices=[LabeledPrice(label="PRO на 1 месяц", amount=80)],
        provider_token="",
    )


@dp.message(Command(commands=["upgrade_plus"]))
async def upgrade_plus(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tier = await get_user_tier(db, uid)
    if tier == Tier.PRO_PLUS:
        await message.answer(
            f"{t('💎 *BTC Monitor* · Подписка', lang)}\n\n{t('У вас уже активна PRO+.', lang)}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="BTC Monitor PRO+",
        description=t("Всё из PRO + голос, confidence score ML, персональный дашборд", lang),
        payload="pro_plus_monthly",
        currency="XTR",
        prices=[LabeledPrice(label="PRO+ на 1 месяц", amount=200)],
        provider_token="",
    )


@dp.message(Command(commands=["donate"]))
async def donate(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=t("☕ Поддержать BTC Monitor", lang),
        description=t("Разработка BTC Monitor — это open-source проект. Ваши Stars помогают покрывать сервер и API.", lang),
        payload="donation",
        currency="XTR",
        prices=[LabeledPrice(label="☕ Чашка кофе для разработчика", amount=10)],
        provider_token="",
    )


@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    payload = message.successful_payment.invoice_payload
    if payload == "donation":
        stars = message.successful_payment.total_amount
        await message.answer(
            f"{t('☕ *BTC Monitor* · Спасибо!', lang)}\n\n"
            f"{t('Спасибо за поддержку ({stars} ⭐)! Ваши Stars пойдут на развитие проекта. ❤️', lang, stars=stars)}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return
    if payload == "pro_monthly":
        await activate_pro(db, uid, days=30)
        label = "PRO"
    elif payload == "pro_plus_monthly":
        await activate_pro_plus(db, uid, days=30)
        label = "PRO+"
    else:
        await message.answer(t("❌ Неизвестный тип подписки.", lang), reply_markup=_menu_kb(lang))
        return
    await message.answer(
        f"{t('✅ *BTC Monitor* · Подписка', lang)}\n\n{t('Оплата прошла! {label} активирован на 30 дней.', lang, label=label)}",
        parse_mode="Markdown",
        reply_markup=_menu_kb(lang),
    )
