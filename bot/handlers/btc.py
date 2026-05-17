from datetime import datetime, timedelta, timezone

from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import Message

from bot.state import analyzer, db, dp, fear_greed, redis_client, _rsi_bar, _tz_for, _ts_from_tz, get_user_lang, _menu_kb
from bot.i18n import t


async def _estimate_hours(db, symbol: str) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = await db.get_1m_candles_since(symbol, since)
    if not rows:
        return 0.0
    times = [r["time"] for r in rows]
    span = (times[-1] - times[0]).total_seconds()
    return span / 3600


async def _estimate_ondays(db) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=60)
    rows = await db.get_all_onchain_metrics_since(since)
    if not rows:
        return 0.0
    times = [r["time"] for r in rows]
    span = (times[-1] - times[0]).total_seconds()
    return span / 86400


_bullish = lambda lang: t("индикаторов за рост", lang)
_bearish = lambda lang: t("индикаторов за снижение", lang)


@dp.message(or_f(Command(commands=["btc"]), F.text == "📊 Аналитика"))
async def btc(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    thinking = await message.answer(t("🧠 Анализирую рынок... ⏳", lang))
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    indicators = await analyzer.compute_indicators()
    price = await db.get_latest_price("BTCUSD")

    if not price:
        await thinking.delete()
        await message.answer(f"❌ {t('Нет данных о цене', lang)}\n\n{ts}", parse_mode="Markdown", reply_markup=_menu_kb(lang))
        return

    pred = await analyzer.predict()

    sig_emoji = "🟢" if pred and pred.direction == "BUY" else "🔴" if pred and pred.direction == "SELL" else "⚪"
    sig_word = "BUY" if pred and pred.direction == "BUY" else "SELL" if pred and pred.direction == "SELL" else "HOLD"

    lines = [f"💰 *BTC Monitor* · Price", "", ts, ""]
    lines.append(f"── {sig_emoji} 𝙎𝙄𝙂𝙉𝘼𝙇: {sig_word} {sig_emoji} ──")
    lines.append("")
    lines.append(f"▸ **BTC/USD:** ${price:,.0f}")

    consensus = await analyzer.compute_consensus()
    if consensus and not consensus.get("low_confidence"):
        cp = consensus["bullish_pct"]
        c_emoji = "🟢" if cp >= 60 else "🔴" if cp <= 40 else "🟡"
        dir_text = _bullish(lang) if cp >= 50 else _bearish(lang)
        lines.append(t("▸ **Консенсус:** {emoji} {pct}% {text}", lang, emoji=c_emoji, pct=cp, text=dir_text))

    if indicators:
        lines.append("")
        lines.append(t("── Технические ──", lang))

        if indicators.rsi is not None:
            lines.append(t("▸ **RSI(14):** {bar}", lang, bar=_rsi_bar(indicators.rsi)))
        else:
            lines.append(f"▸ **RSI(14):** ⏳")

        if indicators.bb_lower is not None and indicators.bb_middle is not None and indicators.bb_upper is not None:
            bb_pos = ""
            if price >= indicators.bb_upper * 0.99:
                bb_pos = t(" ← у верхней", lang)
            elif price <= indicators.bb_lower * 1.01:
                bb_pos = t(" ← у нижней", lang)
            lines.append(t("▸ **BB(20,2):** {lower} / {mid} / {upper}{pos}", lang,
                          lower=f"${indicators.bb_lower:,.0f}", mid=f"${indicators.bb_middle:,.0f}",
                          upper=f"${indicators.bb_upper:,.0f}", pos=bb_pos))

        if indicators.macd is not None:
            macd_dir = ""
            if indicators.macd_signal is not None:
                macd_dir = t(" · бычье", lang) if indicators.macd > indicators.macd_signal else t(" · медвежье", lang)
            sig = f"signal {indicators.macd_signal:+.1f}" if indicators.macd_signal is not None else ""
            hist = f"histogram {indicators.macd_hist:+.1f}" if indicators.macd_hist is not None else ""
            parts = [f"MACD {indicators.macd:+.1f}"]
            if sig:
                parts.append(sig)
            if hist:
                parts.append(hist)
            lines.append(f"▸ **{' · '.join(parts)}**{macd_dir}")

        ma_parts = []
        if indicators.ma_50 is not None:
            ma_parts.append(f"**MA50:** ${indicators.ma_50:,.0f}")
        else:
            ma_parts.append("**MA50:** ⏳ ~50 min")
        if indicators.ma_100 is not None:
            ma_parts.append(f"**MA100:** ${indicators.ma_100:,.0f}")
        if indicators.ma_200 is not None:
            ma_parts.append(f"**MA200:** ${indicators.ma_200:,.0f}")
        else:
            ma_parts.append("**MA200:** ⏳ ~3.5 h")
        lines.append(f"▸ {' | '.join(ma_parts)}")

    if pred and pred.meta:
        p1w = pred.meta.get("prediction_1w")
        if p1w and isinstance(p1w, dict) and p1w.get("mvrv_z") is not None:
            lines.append("")
            lines.append(t("── On-chain ──", lang))
            mvrv = p1w.get("mvrv_z")
            mvrv_int = ""
            if mvrv < 0.5:
                mvrv_int = "недооценён"
            elif mvrv < 3.0:
                mvrv_int = "справедливая оценка"
            elif mvrv < 7.0:
                mvrv_int = "переоценён"
            else:
                mvrv_int = "экстремально переоценён"
            lines.append(t("▸ **MVRV Z-Score:** {score} — {text}", lang, score=f"{mvrv:.2f}", text=t(mvrv_int, lang)))
            phase_label = {
                "ACCUMULATION": "накопление",
                "MARKUP": "рост",
                "DISTRIBUTION": "распределение",
                "MARKDOWN": "снижение",
            }
            phase = p1w.get("cycle_phase", "")
            score = p1w.get("cycle_score", 0)
            if phase:
                phase_word = t(phase_label.get(phase, phase), lang)
                lines.append(t("▸ **Цикл:** {phase} (score {score})", lang, phase=phase_word, score=f"{score:+.2f}"))
        else:
            lines.append("")
            lines.append(t("── On-chain ──", lang))
            lines.append(t("⏳ данные появятся после настройки Glassnode API", lang))

    fng = await fear_greed.fetch()
    if fng:
        lines.append("")
        lines.append(t("── Рынок ──", lang))
        fg_emoji = "🟢" if fng["value"] >= 50 else "🔴"
        lines.append(t("▸ **Fear & Greed:** {emoji} {value}/100 — {text}", lang, emoji=fg_emoji, value=fng['value'], text=fng['classification']))

    try:
        from btcbot.summarizer import summarize_indicators
        onchain_sum = None
        if pred and pred.meta:
            p1w = pred.meta.get("prediction_1w")
            if p1w and isinstance(p1w, dict):
                onchain_sum = {k: p1w.get(k) for k in ("mvrv_z", "sopr", "nupl") if p1w.get(k) is not None}
        summary = await summarize_indicators(db, redis_client, price, indicators, fng, onchain_sum)
        if summary and any(v for v in summary.values()):
            lines.append("")
            lines.append(t("── AI Сводка ──", lang))
            labels = {"trend": t("Тренд", lang), "momentum": t("Моментум", lang), "volatility": t("Волатильность", lang), "onchain": "On-chain", "sentiment": t("Сентимент", lang)}
            for key, text in summary.items():
                if text:
                    lines.append(f"▸ **{labels.get(key, key)}:** {text[:200]}")
    except Exception:
        pass

    lines.append("")
    lines.append(t("♻️ Обновление: реальное время", lang))
    await thinking.delete()
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["predict"]))
async def predict(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    price = await db.get_latest_price("BTCUSD")
    if not price:
        await message.answer(
            f"🔮 *BTC Monitor* · Forecast\n\n{t('⏳ данных пока нет, ожидаем 1–2 мин', lang)}\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return

    hours = await _estimate_hours(db, "BTCUSD")

    pred = await analyzer.predict()

    lines = [f"🔮 *BTC Monitor* · Forecast", "", ts, ""]

    if pred:
        meta = pred.meta or {}
        p4h = meta.get("prediction_4h", {})
        p1w = meta.get("prediction_1w")
        plong = meta.get("prediction_long", {})

        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(pred.direction, "⚪")

        conf_pct = round(pred.confidence * 100)
        conf_color = "🟢" if conf_pct >= 70 else "🟡" if conf_pct >= 40 else "🔴"
        conf_label = t("высокая", lang) if conf_pct >= 70 else t("средняя", lang) if conf_pct >= 40 else t("низкая", lang)

        lines.append("")
        lines.append(t("── Сегодня ──", lang))
        lines.append(f"{emoji} **{pred.direction}** · ${pred.price_min:,.0f}–${pred.price_max:,.0f}")
        lines.append(t("▸ **Уверенность:** {conf}", lang, conf=f"{conf_color} {conf_pct}% — {conf_label}"))

        zones = p4h.get("liquidity_zones", [])
        if zones:
            lines.append("")
            lines.append(t("── Риски ──", lang))
            for z in zones:
                if z["type"] == "long":
                    lines.append(f"▸ retrace to ${z['price']:,.0f} before rally")
                else:
                    lines.append(f"▸ breakout ${z['price']:,.0f} → chain reaction up")

        if p1w and isinstance(p1w, dict) and p1w.get("cycle_phase"):
            lines.append("")
            lines.append(t("── Неделя ──", lang))
            phase_label = {
                "ACCUMULATION": "накопление",
                "MARKUP": "рост",
                "DISTRIBUTION": "распределение",
                "MARKDOWN": "снижение",
            }
            phase_word = t(phase_label.get(p1w["cycle_phase"], "ожидание"), lang)
            week_parts = [f"{phase_word} (score {p1w.get('cycle_score', 0):+.2f})"]
            mvrv = p1w.get("mvrv_z")
            if mvrv is not None:
                week_parts.append(f"MVRV {mvrv:.1f}")
            sopr = p1w.get("sopr")
            if sopr is not None:
                week_parts.append(f"SOPR {sopr:.2f}")
            lines.append(f"▸ {', '.join(week_parts)}")
        elif hours >= 0.5:
            lines.append("")
            lines.append(t("── Неделя ──", lang))
            lines.append(t("⏳ ждём on-chain данные (~24ч)", lang))

        if plong and isinstance(plong, dict):
            long_parts = []
            if plong.get("price_vs_200w_ma_text"):
                txt = plong["price_vs_200w_ma_text"]
                txt = txt.replace("цена на ", "").replace("бычий тренд", t("бычий", lang)).replace("медвежий тренд", t("медвежий", lang)).replace("бычий", t("бычий", lang)).replace("медвежий", t("медвежий", lang))
                long_parts.append(txt)
            hd = plong.get("halving_days")
            if hd is not None:
                long_parts.append(t("халвинг через {d} дн", lang, d=hd))
            if long_parts:
                lines.append("")
                lines.append(t("── Долгосрочно ──", lang))
                lines.append(f"▸ {', '.join(long_parts)}")

        lines.append("")
        lines.append(t("♻️ Обновление: прогноз — 1ч · on-chain — 6ч", lang))
    else:
        lines.append("")
        lines.append(t("── Сегодня ──", lang))
        lines.append(t("⏳ собираем историю для прогноза (~48ч)", lang))
        lines.append("")
        lines.append(t("♻️ пришлю уведомление, когда прогноз будет готов", lang))

    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["volatility"]))
async def volatility(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    tz = await _tz_for(uid)
    ts = _ts_from_tz(tz)
    vol = await analyzer.compute_volatility()
    if not vol:
        await message.answer(
            f"📊 *BTC Monitor* · Volatility\n\n{t('⏳ недостаточно данных', lang)}\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=_menu_kb(lang),
        )
        return
    labels = {"low": t("🟢 Низкая", lang), "medium": t("🟡 Средняя", lang), "high": t("🟠 Высокая", lang), "extreme": t("🔴 Экстремальная", lang)}
    conf_pct = round(vol.current * 100)
    lines = [
        f"📊 *BTC Monitor* · Volatility",
        "",
        ts,
        "",
        t("▸ **Уровень:** {level}", lang, level=f"{labels.get(vol.classification, vol.classification)} · {conf_pct}%"),
        "",
        "── Metrics ──",
        t("▸ **BB ширина:** {pct}% от цены", lang, pct=f"{vol.bb_width_pct:.2f}"),
        t("▸ **ATR(14):** {pct}% от цены", lang, pct=f"{vol.atr_pct:.2f}"),
        t("▸ **Перцентиль (30д):** {pct}%", lang, pct=f"{vol.percentile:.0f}"),
    ]
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=_menu_kb(lang))
