from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.state import db, dp, menu_kb


@dp.message(Command(commands=["subscribe"]))
async def subscribe(message: Message):
    builder = InlineKeyboardBuilder()
    for label, cb in [
        ("RSI — перекупленность/перепроданность", "sub_rsi"),
        ("MA Cross — пересечение MA50 и MA200", "sub_ma_cross"),
        ("Volume Spike — аномальный объём", "sub_volume_spike"),
    ]:
        builder.button(text=label, callback_data=cb)
    builder.adjust(1)
    await message.answer(
        "📢 *BTC Monitor* · Подписка\n\n"
        "Бот пришлёт уведомление при срабатывании:\n\n"
        "• **RSI** — перекупленность (>70) / перепроданность (<30)\n"
        "• **MA Cross** — пересечение MA50 и MA200\n"
        "• **Volume Spike** — объём > 3× среднего\n\n"
        "Выберите тип:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@dp.message(Command(commands=["alerts"]))
async def alerts(message: Message):
    subs = await db.get_user_subscriptions(message.from_user.id)
    if not subs:
        await message.answer("🔔 *BTC Monitor* · Подписки\n\n❌ У вас нет активных подписок", parse_mode="Markdown", reply_markup=menu_kb)
        return

    builder = InlineKeyboardBuilder()
    for sub in subs:
        for at in sub["alert_types"]:
            builder.button(
                text=f"❌ {at} ({sub['symbol']})",
                callback_data=f"del_{sub['id']}_{at}",
            )
    builder.adjust(1)
    await message.answer(
        "🔔 *BTC Monitor* · Подписки\n\n💡 Нажмите ❌ чтобы отписаться:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@dp.callback_query(lambda c: c.data.startswith("sub_"))
async def handle_subscribe(callback: CallbackQuery):
    alert_type = callback.data.split("_", 1)[1]
    await db.upsert_user(callback.from_user.id, callback.from_user.username)
    await db.add_subscription(callback.from_user.id, "BTCUSD", "15m", [alert_type])
    await callback.answer("Подписка оформлена!")
    await callback.message.edit_text(f"✅ *BTC Monitor* · Подписка\n\n💡 Подписка на *{alert_type}* оформлена", parse_mode="Markdown")


@dp.callback_query(lambda c: c.data.startswith("del_"))
async def handle_delete(callback: CallbackQuery):
    parts = callback.data.split("_", 2)
    sub_id = int(parts[1])
    alert_type = parts[2] if len(parts) > 2 else ""
    if alert_type:
        await db.remove_alert_type(sub_id, alert_type)
    else:
        await db.delete_subscription(sub_id)
    await callback.answer("Подписка обновлена")
    await callback.message.edit_text("✅ *BTC Monitor* · Подписки\n\n💡 Подписка обновлена", parse_mode="Markdown")
