import re

from aiogram.filters import Command
from aiogram.types import Message

from bot.state import db, dp, _menu_kb, _tz_for, _ts_from_tz, get_user_lang
from bot.i18n import t


@dp.message(Command(commands=["alert"]))
async def set_alert(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    text = message.text.strip()
    args = text.removeprefix("/alert").strip()

    if not args:
        await message.answer(
            f"🚨 *BTC Monitor* · Price Alert\n\n"
            f"I'll notify you when BTC hits a target price.\n\n"
            f"▪ `/alert 100000` — crosses $100K\n"
            f"▪ `/alert above 100000` — goes above\n"
            f"▪ `/alert below 30000` — drops below\n\n"
            f"List: `/alerts`\n"
            f"Remove: `/alert_remove <id>`\n\n"
            f"{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    direction = "any"
    price_str = args
    if args.lower().startswith("above "):
        direction = "above"
        price_str = args[6:].strip()
    elif args.lower().startswith("below "):
        direction = "below"
        price_str = args[6:].strip()

    price_str_clean = price_str.replace(",", "").replace("$", "")
    try:
        target_price = float(price_str_clean)
    except ValueError:
        await message.answer(
            f"❌ *BTC Monitor* · Error\n\n"
            f"Invalid price: `{price_str}`\n"
            f"Example: `/alert 50000`\n\n"
            f"{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    if target_price <= 0:
        await message.answer(
            f"❌ Price must be positive\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    await db.upsert_user(uid, message.from_user.username)
    alert_id = await db.add_price_alert(uid, target_price, direction)

    dir_text = {"above": t("выше", lang), "below": t("ниже", lang), "any": t("пересечёт", lang)}[direction]
    await message.answer(
        f"✅ *BTC Monitor* · Price Alert\n\n"
        f"🔔 I'll notify when BTC goes **{dir_text}** ${target_price:,.0f}\n"
        f"🆔 ID: {alert_id}\n\n"
        f"Remove: `/alert_remove {alert_id}`\n\n"
        f"{ts}",
        parse_mode="Markdown",
        reply_markup=_menu_kb(lang),
    )


@dp.message(Command(commands=["alert_remove"]))
async def remove_alert(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    text = message.text.strip()
    args = text.removeprefix("/alert_remove").strip()

    if not args:
        await message.answer(
            f"❌ Specify alert ID: `/alert_remove <id>`\n\n"
            f"List: `/alerts`\n\n"
            f"{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    try:
        alert_id = int(args)
    except ValueError:
        await message.answer(
            f"❌ Invalid ID: `{args}`\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    await db.delete_price_alert(alert_id)
    await message.answer(
        f"✅ *BTC Monitor* · Price Alert\n\n"
        f"Alert #{alert_id} removed\n\n"
        f"{ts}",
        parse_mode="Markdown",
        reply_markup=_menu_kb(lang),
    )
