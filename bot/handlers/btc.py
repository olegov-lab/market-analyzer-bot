from datetime import datetime, timedelta, timezone

from aiogram.filters import Command
from aiogram.types import Message

from bot.state import analyzer, db, dp, menu_kb, _ts, _rsi_bar


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


@dp.message(Command(commands=["btc"]))
async def btc(message: Message):
    indicators = await analyzer.compute_indicators()
    price = await db.get_latest_price("BTCUSD")

    if not price:
        await message.answer(f"❌ Нет данных о цене\n\n{_ts()}", parse_mode="Markdown", reply_markup=menu_kb)
        return

    pred = await analyzer.predict()

    sig_emoji = "🟢" if pred and pred.direction == "BUY" else "🔴" if pred and pred.direction == "SELL" else "⚪"
    sig_word = "BUY" if pred and pred.direction == "BUY" else "SELL" if pred and pred.direction == "SELL" else "HOLD"

    lines = [f"💰 *BTC Monitor* · Цена", "", _ts(), ""]
    lines.append(f"── {sig_emoji} 𝙎𝙄𝙂𝙉𝘼𝙇: {sig_word} {sig_emoji} ──")
    lines.append("")
    lines.append(f"▸ **BTC/USD:** ${price:,.0f}")

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

    lines.append("")
    lines.append("♻️ Обновление: реальное время")
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)


@dp.message(Command(commands=["predict"]))
async def predict(message: Message):
    price = await db.get_latest_price("BTCUSD")
    if not price:
        await message.answer(
            f"🔮 *BTC Monitor* · Прогноз\n\n⏳ данных пока нет, ожидаем 1–2 мин\n\n{_ts()}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    hours = await _estimate_hours(db, "BTCUSD")

    pred = await analyzer.predict()

    lines = [f"🔮 *BTC Monitor* · Прогноз", "", _ts(), ""]

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
