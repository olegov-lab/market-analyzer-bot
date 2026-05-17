import io
import json
import time

from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from loguru import logger

from backend.agents import ask_agent
from bot.state import analyzer, bot, db, dp, fear_greed, menu_kb, redis_client, _tz_for, _ts_from_tz
from btcbot.config import settings
from btcbot.subscription import has_feature
from btcbot.utils import safe_gather
from bot.handlers.voice import transcribe_voice


PENDING_TTL = 120
PENDING_PREFIX = "btc:ask:pending:"

CHART_RE = __import__("re").compile(r'\[CHART:(\w+):(\w+)\]')


def _rule_based_analysis(price: float | None, ind: dict | None, fng: dict | None, consensus: dict | None, vol) -> str:
    parts = []
    if price:
        parts.append(f"💰 **BTC:** ${price:,.0f}")

    if ind:
        rsi = ind.get("rsi")
        if rsi is not None:
            if rsi < 35:
                rsi_signal = "🟢 перепроданность"
            elif rsi > 65:
                rsi_signal = "🔴 перекупленность"
            else:
                rsi_signal = "⚪ нейтральная зона"
            parts.append(f"📊 **RSI(14):** {rsi:.1f} — {rsi_signal}")

        ma50 = ind.get("ma_50")
        ma200 = ind.get("ma_200")
        if price and ma50:
            above_ma50 = price > ma50
            parts.append(f"📈 **MA50:** ${ma50:,.0f} ({'выше' if above_ma50 else 'ниже'} цены)")
        if price and ma200:
            above_ma200 = price > ma200
            parts.append(f"📈 **MA200:** ${ma200:,.0f} ({'выше' if above_ma200 else 'ниже'} цены)")

    if fng:
        val = fng["value"]
        if val < 25:
            cls = "😱 крайний страх"
        elif val < 45:
            cls = "😟 страх"
        elif val < 55:
            cls = "😐 нейтрально"
        elif val < 75:
            cls = "😊 жадность"
        else:
            cls = "🤩 крайняя жадность"
        parts.append(f"😨 **F&G:** {val}/100 — {cls}")

    if consensus:
        bp = consensus.get("bullish_pct", 50)
        if bp > 60:
            sig = "🟢 бычий"
        elif bp < 40:
            sig = "🔴 медвежий"
        else:
            sig = "⚪ нейтральный"
        parts.append(f"🎯 **Консенсус:** {bp}% за рост — {sig}")

    if vol:
        cls = vol.classification
        if cls == "low":
            vol_signal = "🟢 низкая"
        elif cls == "medium":
            vol_signal = "🟡 средняя"
        elif cls == "high":
            vol_signal = "🔴 высокая"
        else:
            vol_signal = "⚪ неизвестно"
        parts.append(f"🌊 **Волатильность:** {vol_signal}")

    parts.append(f"\n💡 _AI-агент временно недоступен, ответ сформирован по текущим метрикам._")
    return "\n".join(parts)


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
        tz = await _tz_for(message.from_user.id)
        await message.answer(
            "🧠 *BTC Monitor* · Аналитика\n\n"
            "Задай вопрос о Bitcoin и Market-Brain ответит:\n\n"
            "▪ /ask Почему BTC падает?\n"
            "▪ /ask Что такое MVRV?\n"
            "▪ /ask Прогноз на неделю\n"
            "▪ /ask Стоит ли покупать сейчас?\n\n"
            f"{_ts_from_tz(tz)}",
            reply_markup=menu_kb,
        )
        return

    user_id = message.from_user.id
    tz = await _tz_for(user_id)
    ts = _ts_from_tz(tz)

    pending_key = f"{PENDING_PREFIX}{user_id}"
    if redis_client and await redis_client.exists(pending_key):
        await message.answer(
            "⏳ уже отвечаю на предыдущий вопрос",
            reply_markup=menu_kb,
        )
        return

    if redis_client:
        await redis_client.setex(pending_key, PENDING_TTL, "1")

    thinking = await message.answer(
        f"⏳ Анализирую рынок…\n\n{ts}",
        reply_markup=menu_kb,
    )

    ctx_parts = [f"Сегодня {ts}"]
    price = await db.get_latest_price("BTCUSD")
    if price:
        ctx_parts.append(f"Цена BTC: ${price:,.0f}")

    ind = None
    if redis_client:
        try:
            cached_ind = await redis_client.get("indicators:BTCUSD")
            if cached_ind:
                ind = json.loads(cached_ind)
                if ind.get("rsi") is not None:
                    ctx_parts.append(f"RSI(14): {ind['rsi']:.1f}")
                if ind.get("ma_50") is not None:
                    ctx_parts.append(f"MA50: ${ind['ma_50']:,.0f}")
                if ind.get("ma_200") is not None:
                    ctx_parts.append(f"MA200: ${ind['ma_200']:,.0f}")
        except Exception:
            pass

    fng = await fear_greed.fetch()
    if fng:
        ctx_parts.append(f"F&G: {fng['value']}/100 ({fng['classification']})")

    consensus = await analyzer.compute_consensus()
    vol = await analyzer.compute_volatility()

    ctx = " | ".join(ctx_parts)

    import asyncio as _asyncio
    try:
        response = await _asyncio.wait_for(
            ask_agent(
                "marketbrain",
                f"Контекст рынка: {ctx}\n\nВопрос пользователя: {question}\n\nОтветь на русском языке, используя контекст если нужно.",
                temperature=0.7,
            ),
            timeout=120.0,
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
        fallback = _rule_based_analysis(price, ind, fng, consensus, vol)
        await message.answer(
            f"📊 BTC Monitor · Аналитика\n\n{ts}\n\n{fallback}\n\n♻️ Анализ на основе рыночных данных (AI временно недоступен)",
            reply_markup=menu_kb,
        )
        return

    if len(response) > 4000:
        response = response[:4000] + "..."

    clean_response, chart_buttons = _parse_chart_markers(response)
    reply_markup = menu_kb
    if chart_buttons:
        kb = InlineKeyboardMarkup(inline_keyboard=[[b] for b in chart_buttons])
        reply_markup = kb

    await message.answer(
        f"🧠 BTC Monitor · Аналитика\n\n{ts}\n\n{clean_response}\n\n♻️ Отвечает Market-Brain на базе AI",
        reply_markup=reply_markup,
    )


@dp.message(F.voice)
async def voice_ask(message: Message):
    user_id = message.from_user.id
    tz = await _tz_for(user_id)
    ts = _ts_from_tz(tz)
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
    status_msg = await message.answer("🎤 Распознаю голос...\n\n" + ts, reply_markup=menu_kb)

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

        await status_msg.edit_text(f"🗣 *{text[:200]}{'...' if len(text) > 200 else ''}*\n\n⏳ Анализирую...\n\n{ts}", parse_mode="Markdown", reply_markup=menu_kb)
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
            ctx += f"Fear & Greed: {fng['value']}/100 ({fng['classification']})\n"

        answer = await ask_agent("marketbrain", f"{ctx}\nUser asked via voice: {text}")
        await status_msg.delete()

        if not answer or "[Agent error:" in answer:
            ind_dict = {"rsi": indicators.rsi, "ma_50": indicators.ma_50, "ma_200": indicators.ma_200} if indicators else None
            vol = await analyzer.compute_volatility()
            consensus = await analyzer.compute_consensus()
            fallback = _rule_based_analysis(price, ind_dict, fng, consensus, vol)
            await message.answer(
                f"📊 BTC Monitor · Аналитика\n\n{ts}\n\n{fallback}\n\n♻️ Анализ на основе рыночных данных (AI временно недоступен)",
                reply_markup=menu_kb,
            )
        else:
            parsed_text, chart_markers = _parse_chart_markers(answer)
            reply_markup = menu_kb
            if chart_markers:
                reply_markup = InlineKeyboardMarkup(inline_keyboard=[[b] for b in chart_markers])
            text_to_send = parsed_text[:4000]
            await message.answer(text_to_send, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error("Voice handler error: {}", e)
        try:
            await status_msg.edit_text("❌ Ошибка обработки голоса.", reply_markup=menu_kb)
        except Exception:
            pass
    finally:
        if redis_client:
            await redis_client.delete(pending_key)
