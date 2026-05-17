from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.state import dp, get_user_lang
from bot.i18n import t
from btcbot.lessons import LESSONS


@dp.message(Command(commands=["learn"]))
async def learn_cmd(message: Message):
    lang = await get_user_lang(message.from_user.id)
    builder = InlineKeyboardBuilder()
    for lesson in LESSONS:
        builder.button(
            text=f"{lesson['id']}. {lesson['title']}",
            callback_data=f"lesson_{lesson['id']}",
        )
    builder.adjust(2)
    await message.answer(
        f"{t('📖 *BTC Monitor* · Азбука крипты', lang)}\n\n"
        f"{t('20 уроков для начинающих + 20 для опытных + 20 для профи', lang)}\n\n"
        "• How to read indicators\n"
        "• On-chain metrics\n"
        "• Volume analysis\n\n"
        f"{'Choose a lesson:' if lang == 'en' else 'Выберите урок:'}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@dp.callback_query(lambda c: c.data.startswith("lesson_"))
async def show_lesson(callback: CallbackQuery):
    lesson_id = int(callback.data.split("_")[1])
    lesson = next((l for l in LESSONS if l["id"] == lesson_id), None)
    if not lesson:
        await callback.answer("Урок не найден")
        return

    builder = InlineKeyboardBuilder()
    if lesson_id > 1:
        builder.button(text="◀️", callback_data=f"lesson_{lesson_id - 1}")
    builder.button(text="📋", callback_data="learn_list")
    if lesson_id < len(LESSONS):
        builder.button(text="▶️", callback_data=f"lesson_{lesson_id + 1}")
    builder.adjust(3)

    await callback.message.edit_text(lesson["text"], reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "learn_list")
async def learn_list(callback: CallbackQuery):
    from bot.state import get_user_lang
    from bot.i18n import t
    lang = await get_user_lang(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    for lesson in LESSONS:
        builder.button(
            text=f"{lesson['id']}. {lesson['title']}",
            callback_data=f"lesson_{lesson['id']}",
        )
    builder.adjust(2)
    await callback.message.edit_text(
        f"{t('📖 *BTC Monitor* · Азбука крипты', lang)}\n\n"
        f"{t('20 уроков для начинающих + 20 для опытных + 20 для профи', lang)}\n\n"
        "• How to read indicators\n"
        "• On-chain metrics\n"
        "• Volume analysis\n\n"
        f"{'Choose a lesson:' if lang == 'en' else 'Выберите урок:'}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()
