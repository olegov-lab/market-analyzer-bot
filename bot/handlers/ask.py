from datetime import datetime, timezone

from aiogram.filters import Command
from aiogram.types import Message

from backend.agents import ask_agent
from bot.state import dp, menu_kb, _ts

_user_last_ask: dict[int, datetime] = {}
ASK_COOLDOWN = 30


@dp.message(Command(commands=["ask"]))
async def ask(message: Message):
    text = message.text.strip()
    question = text.removeprefix("/ask").strip()

    if not question:
        await message.answer(
            f"🧠 *BTC Monitor* · Аналитика\n\n"
            f"Задай вопрос о Bitcoin и Market-Brain ответит:\n\n"
            f"▪ `/ask Почему BTC падает?`\n"
            f"▪ `/ask Что такое MVRV?`\n"
            f"▪ `/ask Прогноз на неделю`\n"
            f"▪ `/ask Стоит ли покупать сейчас?`\n\n"
            f"{_ts()}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    user_id = message.from_user.id
    now = datetime.now(timezone.utc)
    last = _user_last_ask.get(user_id)
    if last and (now - last).total_seconds() < ASK_COOLDOWN:
        wait = int(ASK_COOLDOWN - (now - last).total_seconds())
        await message.answer(
            f"⏳ *BTC Monitor* · Подожди {wait} сек перед следующим вопросом\n\n{_ts()}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    _user_last_ask[user_id] = now

    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        response = await ask_agent(
            "marketbrain",
            f"Ответь на русском языке. Вопрос пользователя: {question}",
            temperature=0.7,
        )
    except Exception as e:
        response = f"[Agent error: {e}]"

    if not response or response == "[empty response]":
        response = "❌ Агент временно недоступен. Попробуй позже."

    lines = [
        f"🧠 *BTC Monitor* · Аналитика",
        "",
        _ts(),
        "",
        response,
        "",
        "♻️ Отвечает Market-Brain на базе AI",
    ]
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)
