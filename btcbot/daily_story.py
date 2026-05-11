"""Daily AI-generated market story. Broadcast to all active users at 9:00 UTC."""
import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from backend.agents import ask_agent
from btcbot.fear_greed import FearGreedIndex
from btcbot.summarizer import summarize_indicators
from btcbot.utils import safe_gather


STORY_PROMPT = """Ты — Market-Brain. Напиши ежедневный аналитический обзор рынка Bitcoin.

Формат:
- 📈 **Заголовок дня** (одна яркая фраза)
- **Рынок:** 2-3 предложения о движении цены, объёмах, ключевых уровнях
- **Индикаторы:** 2-3 предложения — RSI, MA, BB, консенсус
- **On-chain:** 1-2 предложения — если есть данные
- **Сентимент:** 1 предложение — Fear & Greed
- **Прогноз:** 1-2 предложения — краткосрочный взгляд

Всего 200-300 слов. Пиши на русском. Профессионально, но доступно."""


async def generate_daily_story(db: Any, redis_client: Any, analyzer: Any) -> str:
    cache_key = f"daily:story:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    price, indicators, fng = await safe_gather(
        db.get_latest_price("BTCUSD"),
        analyzer.compute_indicators(),
        FearGreedIndex(redis_client).fetch(),
        log_prefix="daily_story",
    )

    ctx_parts = [f"Дата: {datetime.now(timezone.utc).strftime('%d %B %Y')}"]
    if price:
        ctx_parts.append(f"Цена BTC: ${price:,.0f}")
    if indicators:
        if indicators.rsi is not None:
            ctx_parts.append(f"RSI(14): {indicators.rsi:.1f}")
        if indicators.ma_50 is not None:
            ctx_parts.append(f"MA50: ${indicators.ma_50:,.0f}")
        if indicators.ma_200 is not None:
            ctx_parts.append(f"MA200: ${indicators.ma_200:,.0f}")
        if indicators.macd is not None:
            macd_dir = "бычий" if indicators.macd > indicators.macd_signal else "медвежий" if indicators.macd_signal else "—"
            ctx_parts.append(f"MACD: {macd_dir}")
    if fng:
        ctx_parts.append(f"Fear & Greed: {fng['value']}/100 ({fng['classification']})")
    try:
        consensus = await analyzer.compute_consensus()
        ctx_parts.append(f"Консенсус: {consensus.get('bullish_pct', 50)}% за рост")
    except Exception:
        pass
    try:
        summary = await summarize_indicators(db, redis_client, price, indicators, fng, None)
        for group, text in summary.items():
            if text:
                ctx_parts.append(f"AI-сводка ({group}): {text[:150]}")
    except Exception:
        pass

    ctx = " | ".join(ctx_parts)
    try:
        story = await ask_agent("marketbrain", f"{STORY_PROMPT}\n\nДанные рынка:\n{ctx}", temperature=0.4)
        if story and "[Agent error:" not in story:
            await redis_client.setex(cache_key, 86400, json.dumps(story, ensure_ascii=False))
            return story
    except Exception as e:
        logger.warning(f"Daily story generation failed: {e}")

    fallback = f"📈 *BTC Monitor* · {datetime.now(timezone.utc).strftime('%d %B %Y')}\n\nРынок Bitcoin сегодня. Цена: ${price:,.0f}."
    return fallback
