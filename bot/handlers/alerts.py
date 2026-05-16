from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.state import db, dp, menu_kb, _tz_for, _ts_from_tz


def _h(text: str) -> str:
    """Escape dynamic text for HTML."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
        "📢 <b>BTC Monitor</b> · Подписка\n\n"
        "Бот пришлёт уведомление при срабатывании:\n\n"
        "• <b>RSI</b> — перекупленность (&gt;70) / перепроданность (&lt;30)\n"
        "• <b>MA Cross</b> — пересечение MA50 и MA200\n"
        "• <b>Volume Spike</b> — объём &gt; 3× среднего\n\n"
        "Выберите тип:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@dp.message(Command(commands=["alerts"]))
async def alerts(message: Message):
    uid = message.from_user.id
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    subs = await db.get_user_subscriptions(uid)
    price_alerts_list = await db.get_user_price_alerts(uid)

    if not subs and not price_alerts_list:
        await message.answer(
            "🔔 <b>BTC Monitor</b> · Подписки\n\n"
            "❌ У вас нет активных подписок\n\n"
            "▪ /subscribe — алерты на RSI, MA Cross, Volume\n"
            "▪ /alert 100000 — ценовой сигнал\n\n"
            f"{ts}",
            parse_mode="HTML",
            reply_markup=menu_kb,
        )
        return

    parts = [f"🔔 <b>BTC Monitor</b> · Подписки", "", ts, ""]

    builder = InlineKeyboardBuilder()
    if subs:
        parts.append("── Алерты ──")
        for sub in subs:
            for at in sub["alert_types"]:
                label = {"rsi": "RSI", "ma_cross": "MA Cross", "volume_spike": "Volume Spike"}.get(at, at)
                parts.append(f"▸ {_h(label)} ({_h(sub['symbol'])})")
                builder.button(text=f"❌ {label}", callback_data=f"del_{sub['id']}_{at}")
        parts.append("")

    if price_alerts_list:
        parts.append("── Ценовые сигналы ──")
        for a in price_alerts_list:
            dir_text = {"above": "выше", "below": "ниже", "any": "пересечёт"}.get(a["direction"], "?")
            status = "✅ сработал" if a["triggered"] else "⏳ ожидание"
            parts.append(f"▸ ${a['target_price']:,.0f} ({_h(dir_text)}) — {_h(status)}")
            if not a["triggered"]:
                builder.button(text=f"❌ ${a['target_price']:,.0f}", callback_data=f"del_price_{a['id']}")

    builder.adjust(1)
    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=builder.as_markup())


@dp.callback_query(lambda c: c.data.startswith("sub_"))
async def handle_subscribe(callback: CallbackQuery):
    alert_type = callback.data.split("_", 1)[1]
    await db.upsert_user(callback.from_user.id, callback.from_user.username)
    await db.add_subscription(callback.from_user.id, "BTCUSD", "15m", [alert_type])
    await callback.answer("Подписка оформлена!")
    await callback.message.edit_text(
        f"✅ <b>BTC Monitor</b> · Подписка\n\n💡 Подписка на <b>{_h(alert_type)}</b> оформлена",
        parse_mode="HTML",
    )


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
    await callback.message.edit_text(
        "✅ <b>BTC Monitor</b> · Подписки\n\n💡 Подписка обновлена",
        parse_mode="HTML",
    )


@dp.callback_query(lambda c: c.data.startswith("del_price_"))
async def handle_delete_price(callback: CallbackQuery):
    alert_id = int(callback.data.split("_")[2])
    await db.delete_price_alert(alert_id)
    await callback.answer("Сигнал удалён")
    await callback.message.edit_text(
        "✅ <b>BTC Monitor</b> · Подписки\n\n💡 Ценовой сигнал удалён",
        parse_mode="HTML",
    )
