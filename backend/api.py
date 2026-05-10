import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database
from btcbot.fear_greed import FearGreedIndex
from btcbot.lessons import LESSONS
from btcbot.news import NEWS_CACHE_TTL, build_sentiment_summary, fetch_news
from btcbot.utils import safe_gather
from backend.miniapp_auth import verify_telegram_init_data
from backend.agents import _get_client, ask_agent, list_agents

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Market Analyzer Bot")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

db = Database(settings.database_url)
redis_client: Optional[aioredis.Redis] = None
analyzer: Optional[Analyzer] = None
fear_greed: Optional[FearGreedIndex] = None

CORS_ORIGIN = settings.miniapp_url_normalized.rstrip("/")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def _get_user_id(request: Request) -> int:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
    if not user:
        raise HTTPException(401, "Invalid init data")
    return user.get("id")


@app.on_event("startup")
async def startup():
    global redis_client, analyzer, fear_greed
    await db.connect()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    analyzer = Analyzer(db, redis_client)
    fear_greed = FearGreedIndex(redis_client)
    asyncio.create_task(analyzer.warmup_cache())
    asyncio.create_task(_cleanup_old_tasks())


@app.on_event("shutdown")
async def shutdown():
    await db.close()
    if redis_client:
        await redis_client.aclose()


@app.get("/")
@limiter.limit("30/minute")
async def root(request: Request):
    return {"status": "backend running"}


@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request):
    return {"status": "ok"}


# ─── Agents API ─────────────────────────────────────────────────────


@app.get("/agents")
@limiter.limit("30/minute")
async def agents_list(request: Request):
    return {"agents": list_agents()}


@app.get("/agents/{name}")
@limiter.limit("30/minute")
async def agents_chat(request: Request, name: str, q: str = ""):
    if not q:
        return {"error": "Query parameter `q` is required"}
    result = await ask_agent(name, q)
    if result is None:
        raise HTTPException(404, f"Agent `{name}` not found")
    return {"response": result}


# ─── BTC Endpoints ──────────────────────────────────────────────────


@app.get("/btc/price")
@limiter.limit("30/minute")
async def btc_price(request: Request):
    price = await db.get_latest_price("BTCUSD")
    if not price:
        raise HTTPException(404, "No price data available")
    return {
        "symbol": "BTCUSD",
        "price": price,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/btc/indicators")
@limiter.limit("30/minute")
async def btc_indicators(request: Request):
    indicators = await analyzer.compute_indicators()
    if not indicators:
        raise HTTPException(503, "Not enough price data to compute indicators")
    return indicators.model_dump()


@app.get("/btc/predict")
@limiter.limit("30/minute")
async def btc_predict(request: Request):
    pred = await analyzer.predict()
    if not pred:
        raise HTTPException(503, "Cannot generate prediction")
    return pred.model_dump()


@app.post("/btc/alert/subscribe")
@limiter.limit("10/minute")
async def subscribe(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    alert_type = body.get("alert_type")
    if not alert_type:
        raise HTTPException(400, "alert_type required")
    await db.upsert_user(user_id)
    await db.add_subscription(user_id, "BTCUSD", "15m", [alert_type])
    return {"status": "subscribed", "user_id": user_id, "alert_type": alert_type}


# ─── Mini App Endpoints ──────────────────────────────────────────────

@app.get("/miniapp/dashboard")
@limiter.limit("30/minute")
async def miniapp_dashboard(request: Request):
    user_id = await _get_user_id(request)
    price, indicators, pred, fng, vol = await safe_gather(
        db.get_latest_price("BTCUSD"),
        analyzer.compute_indicators(),
        analyzer.predict(),
        fear_greed.fetch(),
        analyzer.compute_volatility(),
        log_prefix="dashboard",
    )
    prediction_summary = None
    if pred:
        prediction_summary = {
            "direction": pred.direction,
            "confidence": pred.confidence,
            "price_min": pred.price_min,
            "price_max": pred.price_max,
        }
    vol_data = vol.model_dump() if vol else None
    return {
        "price": price,
        "indicators": indicators.model_dump() if indicators else None,
        "prediction_summary": prediction_summary,
        "fear_greed": fng,
        "volatility": vol_data,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/miniapp/fear-greed")
@limiter.limit("30/minute")
async def miniapp_fear_greed(request: Request):
    user_id = await _get_user_id(request)
    fng = await fear_greed.fetch()
    if not fng:
        raise HTTPException(503, "Fear & Greed data unavailable")
    return fng


@app.get("/miniapp/predict")
@limiter.limit("30/minute")
async def miniapp_predict(request: Request):
    user_id = await _get_user_id(request)
    pred = await analyzer.predict()
    if not pred:
        return None
    return pred.model_dump()


@app.get("/miniapp/news")
@limiter.limit("20/minute")
async def miniapp_news(request: Request):
    articles = await fetch_news(redis_client)
    return build_sentiment_summary(articles)


@app.get("/miniapp/lessons")
@limiter.limit("20/minute")
async def miniapp_lessons(request: Request):
    return [{"id": l["id"], "title": l["title"]} for l in LESSONS]


@app.get("/miniapp/lessons/{lesson_id}")
@limiter.limit("20/minute")
async def miniapp_lesson(request: Request, lesson_id: int):
    lesson = next((l for l in LESSONS if l["id"] == lesson_id), None)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    return lesson


@app.get("/miniapp/subscriptions")
@limiter.limit("20/minute")
async def miniapp_subscriptions(request: Request):
    user_id = await _get_user_id(request)
    subs = await db.get_user_subscriptions(user_id)
    return subs


@app.post("/miniapp/subscriptions")
@limiter.limit("10/minute")
async def miniapp_subscribe(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    alert_type = body.get("alert_type")
    if not alert_type:
        raise HTTPException(400, "alert_type required")
    await db.upsert_user(user_id)
    await db.add_subscription(user_id, "BTCUSD", "15m", [alert_type])
    return {"status": "subscribed", "alert_type": alert_type}


@app.delete("/miniapp/subscriptions/{sub_id}/{alert_type}")
@limiter.limit("10/minute")
async def miniapp_unsubscribe(request: Request, sub_id: int, alert_type: str):
    user_id = await _get_user_id(request)
    await db.remove_alert_type(sub_id, alert_type)
    return {"status": "deleted"}


# ─── Async AI task store (polling-based) ──────────────────────────

_ask_tasks: dict[str, dict] = {}
_ask_tasks_lock = asyncio.Lock()
_ask_task_counter = 0

async def _cleanup_old_tasks():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        async with _ask_tasks_lock:
            expired = [tid for tid, t in _ask_tasks.items() if now - t["created_at"] > 600]
            for tid in expired:
                del _ask_tasks[tid]

async def _run_ask_task(task_id: str, question: str, user_id: int):
    try:
        async with _ask_tasks_lock:
            _ask_tasks[task_id]["status"] = "running"
        price, indicators, fng, pred = await safe_gather(
            db.get_latest_price("BTCUSD"),
            analyzer.compute_indicators(),
            fear_greed.fetch(),
            analyzer.predict(),
            log_prefix="ask_task",
        )
        ctx_parts = [f"Сегодня {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}"]
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
        result = await ask_agent(
            "marketbrain",
            f"Контекст рынка: {ctx}\n\nВопрос пользователя: {question}\n\nОтветь на русском языке, используя контекст если нужно.",
            temperature=0.7,
        )
        async with _ask_tasks_lock:
            if result and "[Agent error:" not in result:
                _ask_tasks[task_id]["status"] = "done"
                _ask_tasks[task_id]["result"] = result
            else:
                _ask_tasks[task_id]["status"] = "error"
                _ask_tasks[task_id]["result"] = "AI agent temporarily unavailable"
    except Exception as e:
        async with _ask_tasks_lock:
            _ask_tasks[task_id]["status"] = "error"
            _ask_tasks[task_id]["result"] = str(e)


@app.post("/miniapp/ask")
@limiter.limit("10/minute")
async def miniapp_ask(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    global _ask_task_counter
    async with _ask_tasks_lock:
        _ask_task_counter += 1
        task_id = f"ask_{_ask_task_counter}_{int(time.time())}"
        _ask_tasks[task_id] = {"status": "pending", "result": None, "created_at": time.time()}
    asyncio.create_task(_run_ask_task(task_id, question, user_id))
    return {"task_id": task_id}


@app.get("/miniapp/ask/{task_id}")
@limiter.limit("120/minute")
async def miniapp_ask_status(request: Request, task_id: str):
    user_id = await _get_user_id(request)
    async with _ask_tasks_lock:
        task = _ask_tasks.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {"status": task["status"], "result": task["result"]}


@app.get("/miniapp/chart")
@limiter.limit("30/minute")
async def miniapp_chart(request: Request, timeframe: str = "4h", limit: int = 100):
    user_id = await _get_user_id(request)
    if timeframe not in ("15m", "1h", "4h", "1d", "1w"):
        raise HTTPException(400, "Invalid timeframe")
    limit = max(10, min(limit, 200))
    cache_key = f"chart:{timeframe}:{limit}"
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    candles = await db.get_candles("BTCUSD", timeframe, limit)
    result = {"candles": candles}
    if redis_client:
        await redis_client.setex(cache_key, 30, json.dumps(result, default=str))
    return result


@app.get("/miniapp/volatility")
@limiter.limit("30/minute")
async def miniapp_volatility(request: Request):
    user_id = await _get_user_id(request)
    vol = await analyzer.compute_volatility()
    if not vol:
        raise HTTPException(503, "Cannot compute volatility data")
    return vol.model_dump()


@app.get("/miniapp/news/timothy")
@limiter.limit("10/minute")
async def miniapp_news_timothy(request: Request):
    user_id = await _get_user_id(request)
    cache_key = "news:timothy"
    if redis_client:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    system_prompt = (
        "You are Timothy Peterson, a renowned Bitcoin analyst and author of the paper "
        "'Metcalfe's Law as a Model for Bitcoin's Value'. You are known for the Lowest Price "
        "Forward (LPF) indicator and modeling BTC price using network effects. "
        "Your analysis style: data-driven, quantitative, skeptical of hype, focused on long-term "
        "trends, Metcalfe's Law, hash rate, and adoption curves. Answer in Russian, "
        "be concise (300-400 words). Provide a current Bitcoin market analysis in your signature style — "
        "include perspective on valuation vs Metcalfe's Law, key support/resistance levels, "
        "and a short-term outlook."
    )
    prompt = (
        "Give a brief Bitcoin market analysis in your signature Timothy Peterson style. "
        "Include your view on current valuation relative to Metcalfe's Law, "
        "key support/resistance levels, and near-term outlook. "
        "Write in Russian, 300-400 words, factual with numbers where relevant."
    )
    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2048,
        )
        text = resp.choices[0].message.content or ""
        result = {"text": text, "source": "Timothy Peterson via AI"}
    except Exception as e:
        logger.error(f"Timothy news agent error: {e}")
        result = {"text": f"Не удалось получить анализ. Попробуйте позже.", "source": "error"}

    if redis_client:
        await redis_client.setex(cache_key, 3600, json.dumps(result, ensure_ascii=False))
    return result


# ─── Static files for Mini App ─────────────────────────────────────

@app.get("/miniapp")
@app.get("/miniapp/{full_path:path}")
@limiter.limit("60/minute")
async def miniapp_static(request: Request, full_path: str = ""):
    base = os.path.join(os.path.dirname(__file__), "..", "miniapp")
    if not full_path:
        file_path = os.path.join(base, "index.html")
    else:
        file_path = os.path.join(base, full_path)
        if not os.path.isfile(file_path):
            file_path = os.path.join(base, "index.html")
    if os.path.isfile(file_path):
        headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        return FileResponse(file_path, headers=headers)
    raise HTTPException(404, "Not found")
