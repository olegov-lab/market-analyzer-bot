from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.state import dp
from btcbot.lessons import LESSONS


@dp.message(Command(commands=["learn"]))
async def learn_cmd(message: Message):
    builder = InlineKeyboardBuilder()
    for lesson in LESSONS:
        builder.button(
            text=f"{lesson['id']}. {lesson['title']}",
            callback_data=f"lesson_{lesson['id']}",
        )
    builder.adjust(2)
    await message.answer(
        "📖 *BTC Monitor* · Азбука крипты\n\n"
        "20 уроков для начинающих + 20 для опытных "
        "+ 20 для профи (ML, аналитика, графики):\n\n"
        "• Как читать индикаторы\n"
        "• On-chain метрики\n"
        "• Анализ объёма\n\n"
        "Выберите урок:",
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
    builder = InlineKeyboardBuilder()
    for lesson in LESSONS:
        builder.button(
            text=f"{lesson['id']}. {lesson['title']}",
            callback_data=f"lesson_{lesson['id']}",
        )
    builder.adjust(2)
    await callback.message.edit_text(
        "📖 *BTC Monitor* · Азбука крипты\n\n"
        "20 уроков для начинающих + 20 для опытных "
        "+ 20 для профи (ML, аналитика, графики):\n\n"
        "• Как читать индикаторы\n"
        "• On-chain метрики\n"
        "• Анализ объёма\n\n"
        "Выберите урок:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()
