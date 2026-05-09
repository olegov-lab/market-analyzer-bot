import json
import os
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database
from btcbot.news import NEWS_CACHE_TTL, build_sentiment_summary, fetch_news
from backend.miniapp_auth import verify_telegram_init_data

app = FastAPI(title="Market Analyzer Bot")

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


@app.on_event("shutdown")
async def shutdown():
    await db.close()
    if redis_client:
        await redis_client.aclose()


@app.get("/")
def root():
    return {"status": "backend running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/btc/price")
async def btc_price():
    price = await db.get_latest_price("BTCUSD")
    if not price:
        raise HTTPException(404, "No price data available")
    return {
        "symbol": "BTCUSD",
        "price": price,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/btc/indicators")
async def btc_indicators():
    indicators = await analyzer.compute_indicators()
    if not indicators:
        raise HTTPException(503, "Not enough price data to compute indicators")
    return indicators.model_dump()


@app.get("/btc/predict")
async def btc_predict():
    pred = await analyzer.predict()
    if not pred:
        raise HTTPException(503, "Cannot generate prediction")
    return pred.model_dump()


@app.post("/btc/alert/subscribe")
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
async def miniapp_dashboard(request: Request):
    user_id = await _get_user_id(request)
    price = await db.get_latest_price("BTCUSD")
    indicators = await analyzer.compute_indicators()
    pred = await analyzer.predict()
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
async def miniapp_predict(request: Request):
    user_id = await _get_user_id(request)
    pred = await analyzer.predict()
    if not pred:
        return None
    return pred.model_dump()


@app.get("/miniapp/news")
async def miniapp_news():
    articles = await fetch_news(redis_client)
    return build_sentiment_summary(articles)


@app.get("/miniapp/lessons")
async def miniapp_lessons():
    return [{"id": l["id"], "title": l["title"]} for l in LESSONS]


@app.get("/miniapp/lessons/{lesson_id}")
async def miniapp_lesson(lesson_id: int):
    lesson = next((l for l in LESSONS if l["id"] == lesson_id), None)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    return lesson


@app.get("/miniapp/subscriptions")
async def miniapp_subscriptions(request: Request):
    user_id = await _get_user_id(request)
    subs = await db.get_user_subscriptions(user_id)
    return subs


@app.post("/miniapp/subscriptions")
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
async def miniapp_unsubscribe(request: Request, sub_id: int, alert_type: str):
    user_id = await _get_user_id(request)
    await db.remove_alert_type(sub_id, alert_type)
    return {"status": "deleted"}


# ─── Static files for Mini App ─────────────────────────────────────

@app.get("/miniapp")
@app.get("/miniapp/{full_path:path}")
async def miniapp_static(full_path: str = ""):
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
