import asyncio
import json
import os
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
from btcbot.news import NEWS_CACHE_TTL, build_sentiment_summary, fetch_news
from backend.miniapp_auth import verify_telegram_init_data
from backend.agents import ask_agent, list_agents

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Market Analyzer Bot")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

db = Database(settings.database_url)
redis_client: Optional[aioredis.Redis] = None
analyzer: Optional[Analyzer] = None

CORS_ORIGIN = settings.miniapp_url_normalized.rstrip("/")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

with open("bot/lessons.json", encoding="utf-8") as f:
    LESSONS = json.load(f)


async def _get_user_id(request: Request) -> int:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
    if not user:
        raise HTTPException(401, "Invalid init data")
    return user.get("id")


@app.on_event("startup")
async def startup():
    global redis_client, analyzer
    await db.connect()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    analyzer = Analyzer(db, redis_client)
    asyncio.create_task(_warmup_cache())


async def _warmup_cache():
    await asyncio.sleep(1)
    try:
        _ = await analyzer.compute_indicators()
        _ = await analyzer.predict()
        logger.info("Backend cache warmed up")
    except Exception as e:
        logger.warning("Backend warmup incomplete: {}", e)


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
    price, indicators, pred = await asyncio.gather(
        db.get_latest_price("BTCUSD"),
        analyzer.compute_indicators(),
        analyzer.predict(),
    )
    prediction_summary = None
    if pred:
        prediction_summary = {
            "direction": pred.direction,
            "confidence": pred.confidence,
            "price_min": pred.price_min,
            "price_max": pred.price_max,
        }
    return {
        "price": price,
        "indicators": indicators.model_dump() if indicators else None,
        "prediction_summary": prediction_summary,
        "time": datetime.now(timezone.utc).isoformat(),
    }


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
