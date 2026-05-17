from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.state import db, dp, _menu_kb, _tz_for, _ts_from_tz, get_user_lang
from bot.i18n import t


def _h(text: str) -> str:
    """Escape dynamic text for HTML."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dp.message(Command(commands=["subscribe"]))
async def subscribe(message: Message):
    lang = await get_user_lang(message.from_user.id)
    builder = InlineKeyboardBuilder()
    for label, cb in [
        ("RSI — overbought/oversold", "sub_rsi"),
        ("MA Cross — MA50 & MA200 crossover", "sub_ma_cross"),
        ("Volume Spike — abnormal volume", "sub_volume_spike"),
    ]:
        builder.button(text=label, callback_data=cb)
    builder.adjust(1)
    await message.answer(
        "📢 <b>BTC Monitor</b> · Subscription\n\n"
        "Bot will notify you when:\n\n"
        "• <b>RSI</b> — overbought (&gt;70) / oversold (&lt;30)\n"
        "• <b>MA Cross</b> — MA50 & MA200 cross\n"
        "• <b>Volume Spike</b> — volume &gt; 3× average\n\n"
        "Choose type:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@dp.message(Command(commands=["alerts"]))
async def alerts(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    subs = await db.get_user_subscriptions(uid)
    price_alerts_list = await db.get_user_price_alerts(uid)

    if not subs and not price_alerts_list:
        await message.answer(
            "🔔 <b>BTC Monitor</b> · Subscriptions\n\n"
            "❌ No active subscriptions\n\n"
            "▪ /subscribe — RSI, MA Cross, Volume alerts\n"
            "▪ /alert 100000 — price alert\n\n"
            f"{ts}",
            parse_mode="HTML",
            reply_markup=_menu_kb(lang),
        )
        return

    parts = [f"🔔 <b>BTC Monitor</b> · Subscriptions", "", ts, ""]

    builder = InlineKeyboardBuilder()
    if subs:
        parts.append("── Alerts ──")
        for sub in subs:
            for at in sub["alert_types"]:
                label = {"rsi": "RSI", "ma_cross": "MA Cross", "volume_spike": "Volume Spike"}.get(at, at)
                parts.append(f"▸ {_h(label)} ({_h(sub['symbol'])})")
                builder.button(text=f"❌ {label}", callback_data=f"del_{sub['id']}_{at}")
        parts.append("")

    if price_alerts_list:
        parts.append("── Price Alerts ──")
        for a in price_alerts_list:
            dir_text = {"above": t("выше", lang), "below": t("ниже", lang), "any": t("пересечёт", lang)}.get(a["direction"], "?")
            status = "✅ triggered" if a["triggered"] else "⏳ waiting"
            parts.append(f"▸ ${a['target_price']:,.0f} ({_h(dir_text)}) — {_h(status)}")
            if not a["triggered"]:
                builder.button(text=f"❌ ${a['target_price']:,.0f}", callback_data=f"del_price_{a['id']}")

    builder.adjust(1)
    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=builder.as_markup())


@dp.callback_query(lambda c: c.data.startswith("sub_"))
async def handle_subscribe(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    alert_type = callback.data.split("_", 1)[1]
    await db.upsert_user(callback.from_user.id, callback.from_user.username)
    await db.add_subscription(callback.from_user.id, "BTCUSD", "15m", [alert_type])
    await callback.answer("Subscribed!" if lang == "en" else "Подписка оформлена!")
    await callback.message.edit_text(
        f"✅ <b>BTC Monitor</b> · Subscription\n\n💡 Subscribed to <b>{_h(alert_type)}</b>",
        parse_mode="HTML",
    )


@dp.callback_query(lambda c: c.data.startswith("del_"))
async def handle_delete(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    parts = callback.data.split("_", 2)
    sub_id = int(parts[1])
    alert_type = parts[2] if len(parts) > 2 else ""
    if alert_type:
        await db.remove_alert_type(sub_id, alert_type)
    else:
        await db.delete_subscription(sub_id)
    await callback.answer("Subscription updated" if lang == "en" else "Подписка обновлена")
    await callback.message.edit_text(
        "✅ <b>BTC Monitor</b> · Subscriptions\n\n💡 Subscription updated",
        parse_mode="HTML",
    )


@dp.callback_query(lambda c: c.data.startswith("del_price_"))
async def handle_delete_price(callback: CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    alert_id = int(callback.data.split("_")[2])
    await db.delete_price_alert(alert_id)
    await callback.answer("Alert removed" if lang == "en" else "Сигнал удалён")
    await callback.message.edit_text(
        "✅ <b>BTC Monitor</b> · Subscriptions\n\n💡 Price alert removed",
        parse_mode="HTML",
    )
