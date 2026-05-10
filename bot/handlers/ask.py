from aiogram.filters import Command
from aiogram.types import Message

from backend.agents import ask_agent
from btcbot.utils import safe_gather
from bot.state import analyzer, db, dp, fear_greed, menu_kb, _ts

_user_pending: set[int] = set()


@dp.message(Command(commands=["ask"]))
async def ask(message: Message):
    text = message.text.strip()
    question = text.removeprefix("/ask").strip()

    if not question:
        await message.answer(
            "🧠 BTC Monitor · Аналитика\n\n"
            "Задай вопрос о Bitcoin и Market-Brain ответит:\n\n"
            "▪ /ask Почему BTC падает?\n"
            "▪ /ask Что такое MVRV?\n"
            "▪ /ask Прогноз на неделю\n"
            "▪ /ask Стоит ли покупать сейчас?\n\n"
            f"{_ts()}",
            reply_markup=menu_kb,
        )
        return

    user_id = message.from_user.id

    if user_id in _user_pending:
        await message.answer(
            "⏳ уже отвечаю на предыдущий вопрос",
            reply_markup=menu_kb,
        )
        return

    _user_pending.add(user_id)

    thinking = await message.answer(
        f"⏳ Анализирую рынок…\n\n{_ts()}",
        reply_markup=menu_kb,
    )

    price, indicators, fng, pred = await safe_gather(
        db.get_latest_price("BTCUSD"),
        analyzer.compute_indicators(),
        fear_greed.fetch(),
        analyzer.predict(),
        log_prefix="ask",
    )

    ctx_parts = [f"Сегодня {_ts()}"]
    if price:
        ctx_parts.append(f"Цена BTC: ${price:,.0f}")
    if indicators:
        if indicators.rsi is not None:
            ctx_parts.append(f"RSI(14): {indicators.rsi:.1f}")
        if indicators.ma_50 is not None:
            ctx_parts.append(f"MA50: ${indicators.ma_50:,.0f}")
        if indicators.ma_200 is not None:
            ctx_parts.append(f"MA200: ${indicators.ma_200:,.0f}")
    if fng:
        ctx_parts.append(f"Fear & Greed: {fng['value']}/100 ({fng['classification']})")
    if pred:
        ctx_parts.append(f"Сигнал: {pred.direction} (уверенность {pred.confidence:.0%})")
    ctx = " | ".join(ctx_parts)

    try:
        response = await ask_agent(
            "marketbrain",
            f"Контекст рынка: {ctx}\n\nВопрос пользователя: {question}\n\nОтветь на русском языке, используя контекст если нужно.",
            temperature=0.7,
        )
    except Exception:
        response = None

    _user_pending.discard(user_id)

    try:
        await thinking.delete()
    except Exception:
        pass

    if not response or "[Agent error:" in response:
        await message.answer(
            "❌ BTC Monitor · Аналитика\n\n"
            "Агент временно недоступен. Попробуй позже.",
            reply_markup=menu_kb,
        )
        return

    if len(response) > 4000:
        response = response[:4000] + "..."

    await message.answer(
        f"🧠 BTC Monitor · Аналитика\n\n{_ts()}\n\n{response}\n\n♻️ Отвечает Market-Brain на базе AI",
        reply_markup=menu_kb,
    )
