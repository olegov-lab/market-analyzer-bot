import re

from aiogram.filters import Command
from aiogram.types import Message

from bot.state import db, dp, menu_kb, _tz_for, _ts_from_tz


@dp.message(Command(commands=["alert"]))
async def set_alert(message: Message):
    tz = await _tz_for(message.from_user.id)
    ts = _ts_from_tz(tz)
    text = message.text.strip()
    args = text.removeprefix("/alert").strip()

    if not args:
        await message.answer(
            f"🚨 *BTC Monitor* · Ценовой сигнал\n\n"
            f"Я оповещу, когда BTC достигнет нужной цены.\n\n"
            f"▪ `/alert 100000` — при пересечении $100K\n"
            f"▪ `/alert above 100000` — когда будет выше\n"
            f"▪ `/alert below 30000` — когда упадёт ниже\n\n"
            f"Список: `/alerts`\n"
            f"Удалить: `/alert_remove <id>`\n\n"
            f"{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
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
            f"❌ *BTC Monitor* · Ошибка\n\n"
            f"Некорректная цена: `{price_str}`\n"
            f"Пример: `/alert 50000`\n\n"
            f"{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    if target_price <= 0:
        await message.answer(
            f"❌ Цена должна быть положительным числом\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    await db.upsert_user(message.from_user.id, message.from_user.username)
    alert_id = await db.add_price_alert(message.from_user.id, target_price, direction)

    dir_text = {"above": "выше", "below": "ниже", "any": "пересечёт"}[direction]
    await message.answer(
        f"✅ *BTC Monitor* · Ценовой сигнал\n\n"
        f"🔔 Я оповещу, когда BTC будет **{dir_text}** ${target_price:,.0f}\n"
        f"🆔 ID: {alert_id}\n\n"
        f"Удалить: `/alert_remove {alert_id}`\n\n"
        f"{ts}",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )


@dp.message(Command(commands=["alert_remove"]))
async def remove_alert(message: Message):
    tz = await _tz_for(message.from_user.id)
    ts = _ts_from_tz(tz)
    text = message.text.strip()
    args = text.removeprefix("/alert_remove").strip()

    if not args:
        await message.answer(
            f"❌ Укажи ID сигнала: `/alert_remove <id>`\n\n"
            f"Список: `/alerts`\n\n"
            f"{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    try:
        alert_id = int(args)
    except ValueError:
        await message.answer(
            f"❌ Некорректный ID: `{args}`\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    await db.delete_price_alert(alert_id)
    await message.answer(
        f"✅ *BTC Monitor* · Ценовой сигнал\n\n"
        f"Сигнал #{alert_id} удалён\n\n"
        f"{ts}",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )
