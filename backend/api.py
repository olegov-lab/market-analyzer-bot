import json
import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import redis.asyncio as aioredis
import xml.etree.ElementTree as ET
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database
from backend.miniapp_auth import verify_telegram_init_data

app = FastAPI(title="Market Analyzer Bot")

db = Database(settings.database_url)
redis_client: Optional[aioredis.Redis] = None
analyzer: Optional[Analyzer] = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

with open("bot/lessons.json", encoding="utf-8") as f:
    LESSONS = json.load(f)

NEWS_CACHE_TTL = 300

BULLISH_KEYWORDS = [
    "surge", "rally", "gain", "bull", "buy", "high", "growth", "record",
    "accumulate", "institutional", "etf", "adopt", "upgrade", "partner",
    "inflow", "break", "hold", "support", "momentum", "optimist",
    "рост", "бычий", "накопление", "покупк", "рекорд", "приток",
    "институциональн", "восстановлени", "прорыв", "уверенность",
]

BEARISH_KEYWORDS = [
    "loss", "drop", "fall", "crash", "bear", "sell", "low", "decline",
    "purge", "ban", "hack", "fraud", "regulat", "worry", "fear",
    "liquidate", "downgrade", "revers", "resist", "panic", "capitul",
    "падени", "медвежий", "потер", "слив", "страх", "обвал",
    "ликвидаци", "запрет", "мошенничеств", "регулятор", "паник",
]


class SubscribeRequest(BaseModel):
    alert_type: str


async def _get_user_id(request: Request) -> int:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
    if not user:
        raise HTTPException(401, "Invalid init data")
    return user.get("id")


def _classify_sentiment(title: str) -> str:
    lower = title.lower()
    bull_score = sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
    bear_score = sum(1 for kw in BEARISH_KEYWORDS if kw in lower)
    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"
    return "neutral"


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
async def subscribe(data: SubscribeRequest):
    user_id = data.alert_type
    await db.upsert_user(user_id)
    await db.add_subscription(user_id, "BTCUSD", "15m", [data.alert_type])
    return {"status": "subscribed", "user_id": user_id}


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
    cached = await redis_client.get("btc:news")
    if cached:
        articles = json.loads(cached)
    else:
        rss_url = "https://news.google.com/rss/search?q=bitcoin&hl=ru&gl=RU&ceid=RU:ru"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url) as resp:
                    xml_data = await resp.text()
                    root = ET.fromstring(xml_data)
                    items = root.findall(".//item")[:10]
                    articles = []
                    for item in items:
                        title_el = item.find("title")
                        link_el = item.find("link")
                        source_el = item.find("source")
                        title = title_el.text if title_el is not None else ""
                        url = link_el.text if link_el is not None else ""
                        source = source_el.text if source_el is not None else ""
                        if not title or not url:
                            continue
                        articles.append({"title": title, "source": source, "url": url})
                        if len(articles) >= 5:
                            break
                    for a in articles:
                        a["sentiment"] = _classify_sentiment(a["title"])
                    await redis_client.set("btc:news", json.dumps(articles), ex=NEWS_CACHE_TTL)
        except Exception:
            articles = []

    bull_count = sum(1 for a in articles if a.get("sentiment") == "bullish")
    bear_count = sum(1 for a in articles if a.get("sentiment") == "bearish")
    neutral_count = sum(1 for a in articles if a.get("sentiment") == "neutral")
    total = len(articles)

    if bull_count > bear_count:
        mood = "bullish"
    elif bear_count > bull_count:
        mood = "bearish"
    else:
        mood = "neutral"

    return {
        "articles": articles,
        "sentiment": {
            "bullish": bull_count,
            "bearish": bear_count,
            "neutral": neutral_count,
            "total": total,
            "mood": mood,
        },
    }


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
