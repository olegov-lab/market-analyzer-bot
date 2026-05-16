from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice, ContentType

from bot.state import bot, db, dp, menu_kb
from btcbot.subscription import activate_pro, activate_pro_plus, get_user_tier, Tier, TIER_PRICES


@dp.message(F.content_type == ContentType.WEB_APP_DATA)
async def web_app_data(message: Message):
    import json
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") != "subscribe":
            return
        tier = data.get("tier", "pro")
    except Exception:
        return

    user_tier = await get_user_tier(db, message.from_user.id)
    if tier == "pro" and user_tier in (Tier.PRO, Tier.PRO_PLUS):
        await message.answer("💎 У вас уже активна подписка PRO.", reply_markup=menu_kb)
        return
    if tier == "pro_plus" and user_tier == Tier.PRO_PLUS:
        await message.answer("💎 У вас уже активна подписка PRO+.", reply_markup=menu_kb)
        return

    if tier == "pro":
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="BTC Monitor PRO",
            description="Безлимитный AI-чат, продвинутые алерты, безлимит сделок",
            payload="pro_monthly",
            currency="XTR",
            prices=[LabeledPrice(label="PRO на 1 месяц", amount=80)],
            provider_token="",
        )
    elif tier == "pro_plus":
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="BTC Monitor PRO+",
            description="Всё из PRO + голос, confidence score ML, персональный дашборд",
            payload="pro_plus_monthly",
            currency="XTR",
            prices=[LabeledPrice(label="PRO+ на 1 месяц", amount=200)],
            provider_token="",
        )
    await message.answer("💎 Счёт выставлен в чате выше. Оплатите Telegram Stars для активации.", reply_markup=menu_kb)


@dp.message(Command(commands=["upgrade"]))
async def upgrade(message: Message):
    tier = await get_user_tier(db, message.from_user.id)
    if tier in (Tier.PRO, Tier.PRO_PLUS):
        await message.answer(
            f"💎 *BTC Monitor* · Подписка\n\nУ вас уже активна подписка {tier.value.upper()}.",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return
    await message.answer(
        "💎 *BTC Monitor* · Подписка\n\nВыберите тариф:",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="BTC Monitor PRO",
        description="Безлимитный AI-чат, продвинутые алерты, безлимит сделок",
        payload="pro_monthly",
        currency="XTR",
        prices=[LabeledPrice(label="PRO на 1 месяц", amount=80)],
        provider_token="",
    )


@dp.message(Command(commands=["upgrade_plus"]))
async def upgrade_plus(message: Message):
    tier = await get_user_tier(db, message.from_user.id)
    if tier == Tier.PRO_PLUS:
        await message.answer(
            f"💎 *BTC Monitor* · Подписка\n\nУ вас уже активна PRO+.",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="BTC Monitor PRO+",
        description="Всё из PRO + голос, confidence score ML, персональный дашборд",
        payload="pro_plus_monthly",
        currency="XTR",
        prices=[LabeledPrice(label="PRO+ на 1 месяц", amount=200)],
        provider_token="",
    )


@dp.message(Command(commands=["donate"]))
async def donate(message: Message):
    await bot.send_invoice(
        chat_id=message.chat.id,
        title="☕ Поддержать BTC Monitor",
        description="Разработка BTC Monitor — это open-source проект. "
                    "Ваши Stars помогают покрывать сервер и API.",
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
    payload = message.successful_payment.invoice_payload
    if payload == "donation":
        stars = message.successful_payment.total_amount
        await message.answer(
            f"☕ *BTC Monitor* · Спасибо!\n\n"
            f"Спасибо за поддержку ({stars} ⭐)! Ваши Stars пойдут на развитие проекта. ❤️",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return
    if payload == "pro_monthly":
        await activate_pro(db, message.from_user.id, days=30)
        label = "PRO"
    elif payload == "pro_plus_monthly":
        await activate_pro_plus(db, message.from_user.id, days=30)
        label = "PRO+"
    else:
        await message.answer("❌ Неизвестный тип подписки.", reply_markup=menu_kb)
        return
    await message.answer(
        f"✅ *BTC Monitor* · Подписка\n\nОплата прошла! {label} активирован на 30 дней.",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )
