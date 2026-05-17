from datetime import datetime, timedelta, timezone

from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import Message

from bot.state import analyzer, db, dp, fear_greed, menu_kb, redis_client, _rsi_bar, _tz_for, _ts_from_tz


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


@dp.message(or_f(Command(commands=["btc"]), F.text == "📊 Аналитика"))
async def btc(message: Message):
    thinking = await message.answer("🧠 Анализирую рынок... ⏳")
    tz = await _tz_for(message.from_user.id)
    ts = _ts_from_tz(tz)
    indicators = await analyzer.compute_indicators()
    price = await db.get_latest_price("BTCUSD")

    if not price:
        await thinking.delete()
        await message.answer(f"❌ Нет данных о цене\n\n{ts}", parse_mode="Markdown", reply_markup=menu_kb)
        return

    pred = await analyzer.predict()

    sig_emoji = "🟢" if pred and pred.direction == "BUY" else "🔴" if pred and pred.direction == "SELL" else "⚪"
    sig_word = "BUY" if pred and pred.direction == "BUY" else "SELL" if pred and pred.direction == "SELL" else "HOLD"

    lines = [f"💰 *BTC Monitor* · Цена", "", ts, ""]
    lines.append(f"── {sig_emoji} 𝙎𝙄𝙂𝙉𝘼𝙇: {sig_word} {sig_emoji} ──")
    lines.append("")
    lines.append(f"▸ **BTC/USD:** ${price:,.0f}")

    consensus = await analyzer.compute_consensus()
    if consensus and not consensus.get("low_confidence"):
        cp = consensus["bullish_pct"]
        c_emoji = "🟢" if cp >= 60 else "🔴" if cp <= 40 else "🟡"
        lines.append(f"▸ **Консенсус:** {c_emoji} {cp}% индикаторов за рост")

    if indicators:
        lines.append("")
        lines.append("── Технические ──")

        if indicators.rsi is not None:
            lines.append(f"▸ **RSI(14):** {_rsi_bar(indicators.rsi)}")
        else:
            lines.append(f"▸ **RSI(14):** ⏳")

        if indicators.bb_lower is not None and indicators.bb_middle is not None and indicators.bb_upper is not None:
            bb_pos = ""
            if price >= indicators.bb_upper * 0.99:
                bb_pos = " ← у верхней"
            elif price <= indicators.bb_lower * 1.01:
                bb_pos = " ← у нижней"
            lines.append(f"▸ **BB(20,2):** ${indicators.bb_lower:,.0f} / ${indicators.bb_middle:,.0f} / ${indicators.bb_upper:,.0f}{bb_pos}")

        if indicators.macd is not None:
            macd_dir = ""
            if indicators.macd_signal is not None:
                macd_dir = " · бычье" if indicators.macd > indicators.macd_signal else " · медвежье"
            sig = f"сигнал {indicators.macd_signal:+.1f}" if indicators.macd_signal is not None else ""
            hist = f"гистограмма {indicators.macd_hist:+.1f}" if indicators.macd_hist is not None else ""
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
            ma_parts.append("**MA50:** ⏳ ~50 мин")
        if indicators.ma_100 is not None:
            ma_parts.append(f"**MA100:** ${indicators.ma_100:,.0f}")
        if indicators.ma_200 is not None:
            ma_parts.append(f"**MA200:** ${indicators.ma_200:,.0f}")
        else:
            ma_parts.append("**MA200:** ⏳ ~3.5 ч")
        lines.append(f"▸ {' | '.join(ma_parts)}")

    if pred and pred.meta:
        p1w = pred.meta.get("prediction_1w")
        if p1w and isinstance(p1w, dict) and p1w.get("mvrv_z") is not None:
            lines.append("")
            lines.append("── On-chain ──")
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
            lines.append(f"▸ **MVRV Z-Score:** {mvrv:.2f} — {mvrv_int}")
            phase_label = {
                "ACCUMULATION": "накопление",
                "MARKUP": "рост",
                "DISTRIBUTION": "распределение",
                "MARKDOWN": "снижение",
            }
            phase = p1w.get("cycle_phase", "")
            score = p1w.get("cycle_score", 0)
            if phase:
                lines.append(f"▸ **Цикл:** {phase_label.get(phase, phase)} (score {score:+.2f})")
        else:
            lines.append("")
            lines.append("── On-chain ──")
            lines.append("⏳ данные появятся после настройки Glassnode API")

    fng = await fear_greed.fetch()
    if fng:
        lines.append("")
        lines.append("── Рынок ──")
        fg_emoji = "🟢" if fng["value"] >= 50 else "🔴"
        lines.append(f"▸ **Fear & Greed:** {fg_emoji} {fng['value']}/100 — {fng['classification']}")

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
            lines.append("── AI Сводка ──")
            labels = {"trend": "Тренд", "momentum": "Моментум", "volatility": "Волатильность", "onchain": "On-chain", "sentiment": "Сентимент"}
            for key, text in summary.items():
                if text:
                    lines.append(f"▸ **{labels.get(key, key)}:** {text[:200]}")
    except Exception:
        pass

    lines.append("")
    lines.append("♻️ Обновление: реальное время")
    await thinking.delete()
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)


@dp.message(Command(commands=["predict"]))
async def predict(message: Message):
    tz = await _tz_for(message.from_user.id)
    ts = _ts_from_tz(tz)
    price = await db.get_latest_price("BTCUSD")
    if not price:
        await message.answer(
            f"🔮 *BTC Monitor* · Прогноз\n\n⏳ данных пока нет, ожидаем 1–2 мин\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    hours = await _estimate_hours(db, "BTCUSD")

    pred = await analyzer.predict()

    lines = [f"🔮 *BTC Monitor* · Прогноз", "", ts, ""]

    if pred:
        meta = pred.meta or {}
        p4h = meta.get("prediction_4h", {})
        p1w = meta.get("prediction_1w")
        plong = meta.get("prediction_long", {})

        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(pred.direction, "⚪")

        conf_pct = round(pred.confidence * 100)
        conf_color = "🟢" if conf_pct >= 70 else "🟡" if conf_pct >= 40 else "🔴"
        conf_label = "высокая" if conf_pct >= 70 else "средняя" if conf_pct >= 40 else "низкая"

        lines.append("")
        lines.append("── Сегодня ──")
        lines.append(f"{emoji} **{pred.direction}** · ${pred.price_min:,.0f}–${pred.price_max:,.0f}")
        lines.append(f"▸ **Уверенность:** {conf_color} {conf_pct}% — {conf_label}")

        zones = p4h.get("liquidity_zones", [])
        if zones:
            lines.append("")
            lines.append("── Риски ──")
            for z in zones:
                if z["type"] == "long":
                    lines.append(f"▸ откат до ${z['price']:,.0f} перед ростом")
                else:
                    lines.append(f"▸ пробой ${z['price']:,.0f} → цепная реакция вверх")

        if p1w and isinstance(p1w, dict) and p1w.get("cycle_phase"):
            lines.append("")
            lines.append("── Неделя ──")
            phase_label = {
                "ACCUMULATION": "накопление",
                "MARKUP": "рост",
                "DISTRIBUTION": "распределение",
                "MARKDOWN": "снижение",
            }
            phase_word = phase_label.get(p1w["cycle_phase"], "ожидание")
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
            lines.append("── Неделя ──")
            lines.append("⏳ ждём on-chain данные (~24ч)")

        if plong and isinstance(plong, dict):
            long_parts = []
            if plong.get("price_vs_200w_ma_text"):
                txt = plong["price_vs_200w_ma_text"]
                txt = txt.replace("цена на ", "").replace("бычий тренд", "бычий").replace("медвежий тренд", "медвежий")
                long_parts.append(txt)
            hd = plong.get("halving_days")
            if hd is not None:
                long_parts.append(f"халвинг через {hd} дн")
            if long_parts:
                lines.append("")
                lines.append("── Долгосрочно ──")
                lines.append(f"▸ {', '.join(long_parts)}")

        lines.append("")
        lines.append("♻️ Обновление: прогноз — 1ч · on-chain — 6ч")
    else:
        lines.append("")
        lines.append("── Сегодня ──")
        lines.append("⏳ собираем историю для прогноза (~48ч)")
        lines.append("")
        lines.append("♻️ пришлю уведомление, когда прогноз будет готов")

    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)


@dp.message(Command(commands=["volatility"]))
async def volatility(message: Message):
    tz = await _tz_for(message.from_user.id)
    ts = _ts_from_tz(tz)
    vol = await analyzer.compute_volatility()
    if not vol:
        await message.answer(
            f"📊 *BTC Monitor* · Волатильность\n\n⏳ недостаточно данных\n\n{ts}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return
    labels = {"low": "🟢 Низкая", "medium": "🟡 Средняя", "high": "🟠 Высокая", "extreme": "🔴 Экстремальная"}
    conf_pct = round(vol.current * 100)
    lines = [
        f"📊 *BTC Monitor* · Волатильность",
        "",
        ts,
        "",
        f"▸ **Уровень:** {labels.get(vol.classification, vol.classification)} · {conf_pct}%",
        "",
        "── Показатели ──",
        f"▸ **BB ширина:** {vol.bb_width_pct:.2f}% от цены",
        f"▸ **ATR(14):** {vol.atr_pct:.2f}% от цены",
        f"▸ **Перцентиль (30д):** {vol.percentile:.0f}%",
    ]
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)
