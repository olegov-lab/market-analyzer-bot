import io
import time

from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from loguru import logger

from backend.agents import ask_agent
from bot.state import analyzer, bot, db, dp, fear_greed, menu_kb, redis_client, _ts
from btcbot.config import settings
from btcbot.subscription import get_ask_count_today, has_feature, increment_ask_count
from btcbot.utils import safe_gather
from bot.handlers.voice import transcribe_voice


PENDING_TTL = 120
PENDING_PREFIX = "btc:ask:pending:"

CHART_RE = __import__("re").compile(r'\[CHART:(\w+):(\w+)\]')


def _parse_chart_markers(text: str) -> tuple[str, list[InlineKeyboardButton]]:
    buttons = []
    def replacer(m):
        tf, ind = m.group(1), m.group(2)
        url = f"{settings.miniapp_url}#indicators/chart/{tf}/{ind}"
        buttons.append(InlineKeyboardButton(
            text=f"📊 {tf}/{ind}",
            web_app=WebAppInfo(url=url),
        ))
        return f"📊 {tf}/{ind}"
    clean = CHART_RE.sub(replacer, text)
    return clean, buttons


@dp.message(or_f(Command(commands=["ask"]), F.text == "🧠 AI Чат"))
async def ask(message: Message):
    text = message.text.strip()
    question = text.removeprefix("/ask").strip()
    if question == "🧠 AI Чат":
        question = ""

    if not question:
        await message.answer(
            "🧠 *BTC Monitor* · Аналитика\n\n"
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

    # Check rate limit and subscription
    is_pro = await has_feature(db, user_id, "ask_unlimited")
    if not is_pro:
        ask_count = await get_ask_count_today(redis_client, user_id)
        if ask_count >= 3:
            await message.answer(
                "🔒 *BTC Monitor* · Лимит\n\n"
                "3 AI-вопроса в день для бесплатного тарифа.\n\n"
                "🎁 У вас может быть активен 3-дневный PRO триал.\n"
                "💎 Оформите PRO за 80 ⭐ — ∞ вопросов!\n\n"
                "/start чтобы проверить триал",
                parse_mode="Markdown",
                reply_markup=menu_kb,
            )
            return

    pending_key = f"{PENDING_PREFIX}{user_id}"
    if redis_client and await redis_client.exists(pending_key):
        await message.answer(
            "⏳ уже отвечаю на предыдущий вопрос",
            reply_markup=menu_kb,
        )
        return

    if redis_client:
        await redis_client.setex(pending_key, PENDING_TTL, "1")
    if not is_pro:
        await increment_ask_count(redis_client, user_id)

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

    if redis_client:
        await redis_client.delete(f"{PENDING_PREFIX}{user_id}")

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

    clean_response, chart_buttons = _parse_chart_markers(response)
    reply_markup = menu_kb
    if chart_buttons:
        kb = InlineKeyboardMarkup(inline_keyboard=[chart_buttons])
        reply_markup = kb

    await message.answer(
        f"🧠 BTC Monitor · Аналитика\n\n{_ts()}\n\n{clean_response}\n\n♻️ Отвечает Market-Brain на базе AI",
        reply_markup=reply_markup,
    )


@dp.message(F.voice)
async def voice_ask(message: Message):
    user_id = message.from_user.id
    is_pro_plus = await has_feature(db, user_id, "voice_input")
    if not is_pro_plus:
        await message.answer(
            "🔒 *BTC Monitor* · Голос\n\n"
            "Голосовой ввод доступен на тарифе PRO+.\n\n"
            "💎 Оформите PRO+ за 200 ⭐/мес — `/upgrade_plus`",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    # Rate limit check
    pending_key = f"{PENDING_PREFIX}{user_id}"
    if redis_client and await redis_client.exists(pending_key):
        await message.answer("⏳ Подождите, обрабатываю предыдущий запрос...", reply_markup=menu_kb)
        return

    if redis_client:
        await redis_client.setex(pending_key, PENDING_TTL, "1")

    await bot.send_chat_action(message.chat.id, "typing")
    status_msg = await message.answer("🎤 Распознаю голос...\n\n" + _ts(), reply_markup=menu_kb)

    try:
        file_info = await bot.get_file(message.voice.file_id)
        file_bytes = await bot.download_file(file_info.file_path)
        buf = io.BytesIO()
        buf.write(file_bytes.read())
        voice_data = buf.getvalue()

        text = await transcribe_voice(voice_data, settings.openai_api_key)

        if not text:
            await status_msg.edit_text("❌ Не удалось распознать голос.", reply_markup=menu_kb)
            if redis_client:
                await redis_client.delete(pending_key)
            return

        await status_msg.edit_text(f"🗣 *{text[:200]}{'...' if len(text) > 200 else ''}*\n\n⏳ Анализирую...\n\n{_ts()}", parse_mode="Markdown", reply_markup=menu_kb)
        await bot.send_chat_action(message.chat.id, "typing")

        price, indicators, fng, pred = await safe_gather(
            db.get_latest_price("BTCUSD"),
            analyzer.compute_indicators(),
            fear_greed.fetch(),
            analyzer.predict(),
            log_prefix="voice_ask",
        )

        ctx = f"Date: {message.date.strftime('%Y-%m-%d %H:%M UTC')}\n"
        if price:
            ctx += f"BTC price: ${price:,.2f}\n"
        if indicators and indicators.rsi is not None:
            ctx += f"RSI(14): {indicators.rsi:.1f} | MA50: ${indicators.ma_50:,.0f} | MA200: ${indicators.ma_200:,.0f}\n" if indicators.ma_50 and indicators.ma_200 else ""
        if fng:
            ctx += f"Fear & Greed: {fng.value}/100 ({fng.classification})\n"

        answer = await ask_agent("marketbrain", f"{ctx}\nUser asked via voice: {text}")
        parsed_text, chart_markers = _parse_chart_markers(answer)
        await status_msg.delete()

        if chart_markers:
            reply_markup = _build_chart_keyboard(chart_markers)
            for chunk in _split_long_message(parsed_text[:4000]):
                await message.answer(chunk, parse_mode="HTML", reply_markup=reply_markup)
        else:
            for chunk in _split_long_message(parsed_text[:4000]):
                await message.answer(chunk, parse_mode="HTML", reply_markup=menu_kb)
    except Exception as e:
        logger.error("Voice handler error: {}", e)
        try:
            await status_msg.edit_text("❌ Ошибка обработки голоса.", reply_markup=menu_kb)
        except Exception:
            pass
    finally:
        if redis_client:
            await redis_client.delete(pending_key)
