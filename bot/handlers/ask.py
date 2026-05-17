import io
import json
import time

from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from loguru import logger

from backend.agents import ask_agent
from bot.state import analyzer, bot, db, dp, fear_greed, redis_client, _tz_for, _ts_from_tz, get_user_lang, _menu_kb
from bot.i18n import t
from btcbot.config import settings
from btcbot.subscription import has_feature
from btcbot.utils import safe_gather
from bot.handlers.voice import transcribe_voice


PENDING_TTL = 120
PENDING_PREFIX = "btc:ask:pending:"

CHART_RE = __import__("re").compile(r'\[CHART:(\w+):(\w+)\]')


def _rule_based_analysis(price: float | None, ind: dict | None, fng: dict | None, consensus: dict | None, vol, lang: str = "ru") -> str:
    parts = []
    if price:
        parts.append(f"💰 **BTC:** ${price:,.0f}")

    if ind:
        rsi = ind.get("rsi")
        if rsi is not None:
            if rsi < 35:
                rsi_signal = t("🟢 перепроданность", lang)
            elif rsi > 65:
                rsi_signal = t("🔴 перекупленность", lang)
            else:
                rsi_signal = t("⚪ нейтральная зона", lang)
            parts.append(f"📊 **RSI(14):** {rsi:.1f} — {rsi_signal}")

        ma50 = ind.get("ma_50")
        ma200 = ind.get("ma_200")
        if price and ma50:
            above_ma50 = price > ma50
            parts.append(f"📈 **MA50:** ${ma50:,.0f} ({t('выше', lang) if above_ma50 else t('ниже', lang)} price)")
        if price and ma200:
            above_ma200 = price > ma200
            parts.append(f"📈 **MA200:** ${ma200:,.0f} ({t('выше', lang) if above_ma200 else t('ниже', lang)} price)")

    if fng:
        val = fng["value"]
        if val < 25:
            cls = t("😱 крайний страх", lang)
        elif val < 45:
            cls = t("😟 страх", lang)
        elif val < 55:
            cls = t("😐 нейтрально", lang)
        elif val < 75:
            cls = t("😊 жадность", lang)
        else:
            cls = t("🤩 крайняя жадность", lang)
        parts.append(f"😨 **F&G:** {val}/100 — {cls}")

    if consensus:
        bp = consensus.get("bullish_pct", 50)
        if bp > 60:
            sig = t("🟢 бычий", lang)
        elif bp < 40:
            sig = t("🔴 медвежий", lang)
        else:
            sig = t("⚪ нейтральный", lang)
        parts.append(f"🎯 **Consensus:** {bp}% up — {sig}")

    if vol:
        cls = vol.classification
        if cls == "low":
            vol_signal = t("🟢 низкая", lang)
        elif cls == "medium":
            vol_signal = t("🟡 средняя", lang)
        elif cls == "high":
            vol_signal = t("🔴 высокая", lang)
        else:
            vol_signal = "⚪ unknown"
        parts.append(f"🌊 **Volatility:** {vol_signal}")

    parts.append(f"\n{t('💡 _AI-агент временно недоступен, ответ сформирован по текущим метрикам._', lang)}")
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
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    text = message.text.strip()
    question = text.removeprefix("/ask").strip()
    if question in ("🧠 AI Чат", "🧠 AI Chat"):
        question = ""

    if not question:
        tz = await _tz_for(uid)
        await message.answer(
            "🧠 *BTC Monitor* · Analytics\n\n"
            "Ask about Bitcoin and Market-Brain will respond:\n\n"
            "▪ /ask Why is BTC falling?\n"
            "▪ /ask What is MVRV?\n"
            "▪ /ask Weekly forecast\n"
            "▪ /ask Should I buy now?\n\n"
            f"{_ts_from_tz(tz)}",
            reply_markup=_menu_kb(lang),
        )
        return

    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)

    pending_key = f"{PENDING_PREFIX}{uid}"
    if redis_client and await redis_client.exists(pending_key):
        await message.answer(
            "⏳ already answering previous question",
            reply_markup=_menu_kb(lang),
        )
        return

    if redis_client:
        await redis_client.setex(pending_key, PENDING_TTL, "1")

    thinking = await message.answer(
        f"⏳ Analyzing market…\n\n{ts}",
        reply_markup=_menu_kb(lang),
    )

    ctx_parts = [f"Today {ts}"]
    price = await db.get_latest_price("BTCUSD")
    if price:
        ctx_parts.append(f"BTC price: ${price:,.0f}")

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

    lang_prompt = "ru" if lang == "ru" else "en"
    import asyncio as _asyncio
    try:
        response = await _asyncio.wait_for(
            ask_agent(
                "marketbrain",
                f"Market context: {ctx}\n\nUser question: {question}\n\nAnswer in {'Russian' if lang_prompt == 'ru' else 'English'}, using the context if needed.",
                temperature=0.7,
            ),
            timeout=120.0,
        )
    except Exception:
        response = None

    if redis_client:
        await redis_client.delete(f"{PENDING_PREFIX}{uid}")

    try:
        await thinking.delete()
    except Exception:
        pass

    if not response or "[Agent error:" in response:
        fallback = _rule_based_analysis(price, ind, fng, consensus, vol, lang)
        await message.answer(
            f"📊 BTC Monitor · Analytics\n\n{ts}\n\n{fallback}\n\n♻️ Analysis based on market data (AI temporarily unavailable)",
            reply_markup=_menu_kb(lang),
        )
        return

    if len(response) > 4000:
        response = response[:4000] + "..."

    clean_response, chart_buttons = _parse_chart_markers(response)
    reply_markup = _menu_kb(lang)
    if chart_buttons:
        kb = InlineKeyboardMarkup(inline_keyboard=[[b] for b in chart_buttons])
        reply_markup = kb

    await message.answer(
        f"🧠 BTC Monitor · Analytics\n\n{ts}\n\n{clean_response}\n\n♻️ Market-Brain AI response",
        reply_markup=reply_markup,
    )


@dp.message(F.voice)
async def voice_ask(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    is_pro_plus = await has_feature(db, uid, "voice_input")
    if not is_pro_plus:
        await message.answer(
            "🔒 *BTC Monitor* · Voice\n\n"
            "Voice input is available on PRO+ plan.\n\n"
            "💎 Get PRO+ for 200 ⭐/month — `/upgrade_plus`",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    # Rate limit check
    pending_key = f"{PENDING_PREFIX}{uid}"
    if redis_client and await redis_client.exists(pending_key):
        await message.answer("⏳ Please wait, processing previous request...", reply_markup=_menu_kb(lang))
        return

    if redis_client:
        await redis_client.setex(pending_key, PENDING_TTL, "1")

    await bot.send_chat_action(message.chat.id, "typing")
    status_msg = await message.answer("🎤 Recognizing voice...\n\n" + ts, reply_markup=_menu_kb(lang))

    try:
        file_info = await bot.get_file(message.voice.file_id)
        file_bytes = await bot.download_file(file_info.file_path)
        buf = io.BytesIO()
        buf.write(file_bytes.read())
        voice_data = buf.getvalue()

        text = await transcribe_voice(voice_data, settings.openai_api_key)

        if not text:
            await status_msg.edit_text("❌ Could not recognize voice.", reply_markup=_menu_kb(lang))
            if redis_client:
                await redis_client.delete(pending_key)
            return

        await status_msg.edit_text(f"🗣 *{text[:200]}{'...' if len(text) > 200 else ''}*\n\n⏳ Analyzing...\n\n{ts}", parse_mode="Markdown", reply_markup=_menu_kb(lang))
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
            fallback = _rule_based_analysis(price, ind_dict, fng, consensus, vol, lang)
            await message.answer(
                f"📊 BTC Monitor · Analytics\n\n{ts}\n\n{fallback}\n\n♻️ Analysis based on market data (AI temporarily unavailable)",
                reply_markup=_menu_kb(lang),
            )
        else:
            parsed_text, chart_markers = _parse_chart_markers(answer)
            reply_markup = _menu_kb(lang)
            if chart_markers:
                reply_markup = InlineKeyboardMarkup(inline_keyboard=[[b] for b in chart_markers])
            text_to_send = parsed_text[:4000]
            await message.answer(text_to_send, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error("Voice handler error: {}", e)
        try:
            await status_msg.edit_text("❌ Voice processing error.", reply_markup=_menu_kb(lang))
        except Exception:
            pass
    finally:
        if redis_client:
            await redis_client.delete(pending_key)
