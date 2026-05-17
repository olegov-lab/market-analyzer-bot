from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.state import db, dp, _clear_tz_cache

TZ_LIST = [
    ("Europe/Moscow", "🇷🇺 Москва (UTC+3)"),
    ("Europe/Kaliningrad", "🇷🇺 Калининград (UTC+2)"),
    ("Europe/Samara", "🇷🇺 Самара (UTC+4)"),
    ("Asia/Yekaterinburg", "🇷🇺 Екатеринбург (UTC+5)"),
    ("Asia/Omsk", "🇷🇺 Омск (UTC+6)"),
    ("Asia/Krasnoyarsk", "🇷🇺 Красноярск (UTC+7)"),
    ("Asia/Irkutsk", "🇷🇺 Иркутск (UTC+8)"),
    ("Asia/Vladivostok", "🇷🇺 Владивосток (UTC+10)"),
    ("Asia/Kamchatka", "🇷🇺 Камчатка (UTC+12)"),
    ("Europe/London", "🇬🇧 Лондон (UTC+0)"),
    ("Europe/Berlin", "🇩🇪 Берлин (UTC+1)"),
    ("Asia/Dubai", "🇦🇪 Дубай (UTC+4)"),
    ("Asia/Almaty", "🇰🇿 Алматы (UTC+5)"),
    ("America/New_York", "🇺🇸 Нью-Йорк (UTC-5)"),
]


@dp.message(Command(commands=["timezone"]))
async def timezone_cmd(message: Message):
    uid = message.from_user.id
    current = await db.get_user_timezone(uid)
    builder = InlineKeyboardBuilder()
    for tz_id, label in TZ_LIST:
        mark = " ✅" if tz_id == current else ""
        builder.button(text=label + mark, callback_data=f"tz_{tz_id}")
    builder.adjust(1)
    await message.answer(
        f"🌍 *BTC Monitor* · Часовой пояс\n\n"
        f"Сейчас: `{current}`\n\n"
        "Выберите ваш часовой пояс:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(lambda c: c.data.startswith("tz_"))
async def timezone_set(callback: CallbackQuery):
    tz = callback.data[3:]
    uid = callback.from_user.id
    await db.set_user_timezone(uid, tz)
    _clear_tz_cache(uid)
    await callback.answer(f"✅ Часовой пояс установлен: {tz}")
    await callback.message.edit_text(
        f"🌍 *BTC Monitor* · Часовой пояс\n\n✅ Установлен: `{tz}`",
        parse_mode="Markdown",
    )
