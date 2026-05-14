from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from btcbot.db import Database

_SUMMARY_PROMPT = """Ты — Market-Brain, криптоаналитик. Напиши КРАТКУЮ (2-3 предложения) сводку по группе индикаторов Bitcoin.

ПРАВИЛА:
- Не перечисляй значения. Интерпретируй смысл.
- Не давай инвестиционных рекомендаций.
- Если данных нет (None/null) — пропусти группу.
- Пиши на русском, профессионально но понятно.

ИНТЕРПРЕТАЦИЯ:
- RSI > 70: перекупленность. < 30: перепроданность.
- MACD > сигнальной: бычий моментум.
- Цена > MA50/MA200: бычий тренд.
- Цена у верхней BB: возможна коррекция. У нижней: возможен отскок.
- MVRV Z < 0.5: недооценён. 0.5-3: справедливо. > 3: переоценён.
- SOPR < 1: держатели фиксируют убытки. > 1: прибыль.
- Fear & Greed < 25: экстремальный страх. > 75: жадность.
- Funding Rate > 0.01%: перегрев лонгов. < -0.01%: перегрев шортов.

СТИЛЬ (готовые шаблоны):
- Тренд: "Бычий тренд укрепляется, цена выше MA50 и MA200. Покупатели контролируют рынок."
- Моментум: "RSI в нейтральной зоне, моментум замедляется. Рынок консолидируется."
- Волатильность: "Полосы Боллинджера сужаются — признак скорого импульсного движения."
- On-chain: "SOPR ниже 1 — держатели фиксируют убытки. Признак капитуляции."
- Сентимент: "Рынок в зоне Extreme Fear. Исторически — момент накопления."""


async def summarize_indicators(
    db: Database,
    redis_client: aioredis.Redis,
    price: Optional[float],
    indicators: Optional[object],
    fng: Optional[dict],
    onchain: Optional[dict],
) -> dict[str, str]:
    """Generate AI summaries for indicator groups. Cached in Redis 5 min."""
    cache_key = "summary:indicators"
    cached = await redis_client.get(cache_key)
    if cached:
        import json
        return json.loads(cached)

    result = {"trend": "", "momentum": "", "volatility": "", "onchain": "", "sentiment": ""}

    if not indicators:
        return result

    try:
        from backend.agents import ask_agent

        groups = {}
        if indicators.ma_50 and indicators.ma_200:
            groups["trend"] = (
                f"Цена BTC: ${price:,.0f}\n"
                f"MA50: ${indicators.ma_50:,.0f}, MA200: ${indicators.ma_200:,.0f}\n"
                f"Цена выше MA50? {'да' if price and price > indicators.ma_50 else 'нет'}. "
                f"Выше MA200? {'да' if price and price > indicators.ma_200 else 'нет'}.\n"
                f"MACD: {indicators.macd:.1f} vs сигнал: {indicators.macd_signal:.1f}"
            )
        if indicators.rsi:
            bb_lower = getattr(indicators, "bb_lower", None)
            bb_middle = getattr(indicators, "bb_middle", None)
            bb_upper = getattr(indicators, "bb_upper", None)
            bb_lower_fmt = f"{bb_lower:,.0f}" if bb_lower else '—'
            bb_middle_fmt = f"{bb_middle:,.0f}" if bb_middle else '—'
            bb_upper_fmt = f"{bb_upper:,.0f}" if bb_upper else '—'
            groups["momentum"] = (
                f"RSI(14): {indicators.rsi:.1f}\n"
                f"BB: ${bb_lower_fmt} / ${bb_middle_fmt} / ${bb_upper_fmt}\n"
                f"Позиция в BB: {((price - bb_lower) / (bb_upper - bb_lower) * 100) if bb_upper and bb_lower else '—'}%"
            )
        if indicators.bb_lower and getattr(indicators, "atr_pct", None):
            bb_lower = getattr(indicators, "bb_lower", None)
            bb_middle = getattr(indicators, "bb_middle", None)
            bb_upper = getattr(indicators, "bb_upper", None)
            groups["volatility"] = (
                f"BB ширина: {(bb_upper - bb_lower) / bb_middle * 100:.1f}%\n"
                f"ATR: {indicators.atr_pct:.1f}% от цены"
            )
        if onchain:
            groups["onchain"] = (
                f"MVRV Z-Score: {onchain.get('mvrv_z', '—')}\n"
                f"SOPR: {onchain.get('sopr', '—')}\n"
                f"NUPL: {onchain.get('nupl', '—')}\n"
                f"Фаза цикла: {onchain.get('cycle_phase', '—')}"
            )
        if fng:
            groups["sentiment"] = (
                f"Fear & Greed: {fng['value']}/100 ({fng['classification']})\n"
                f"Funding Rate: {getattr(indicators, 'funding_rate', None) if indicators else None or '—'}"
            )

        for group_name, data in groups.items():
            try:
                prompt = _SUMMARY_PROMPT + f"\n\nГруппа: {group_name.upper()}\nДанные:\n{data}\n\nСгенерируй сводку ТОЛЬКО для этой группы:"
                response = await ask_agent("marketbrain", prompt, temperature=0.35)
                if response and "[Agent error" not in response:
                    result[group_name] = response.strip()
            except Exception:
                pass

        import json
        await redis_client.setex(cache_key, 300, json.dumps(result, ensure_ascii=False))
    except Exception as e:
        logger.warning("summarize_indicators failed: {}", e)

    return result
