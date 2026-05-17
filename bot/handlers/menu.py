from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.state import dp, get_user_lang, _menu_kb
from bot.i18n import t


@dp.message(lambda m: m.text in ("❓ Ещё", "/help"))
async def menu_help(message: Message):
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        f"{t('❓ *BTC Monitor* · Помощь', lang)}\n\n"
        f"{t('📊 **Mini App** — кнопка `📊 BTC` слева от ввода', lang)}\n\n"
        f"{t('💰 `/btc` — цена и индикаторы', lang)}\n"
        f"{t('🔮 `/predict` — прогноз', lang)}\n"
        f"{t('🧠 `/ask` — AI-аналитик', lang)}\n"
        f"{t('🎮 `/portfolio` — симулятор', lang)}\n"
        f"{t('📰 `/news` — новости', lang)}\n"
        f"{t('📖 `/learn` — азбука', lang)}\n"
        f"{t('🔔 `/subscribe` — уведомления', lang)}\n"
        f"{t('🏆 `/leaderboard` — топ трейдеров', lang)}\n"
        f"{t('👥 `/referral` — привести друга (+5⭐)', lang)}\n"
        f"{t('🌍 `/timezone` — часовой пояс', lang)}\n"
        f"{t('☕ `/donate` — поддержать проект', lang)}\n\n"
        f"{t('♻️ Данные: Binance · Прогноз: 1ч / 6ч', lang)}",
        parse_mode="Markdown",
    )
