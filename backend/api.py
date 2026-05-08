from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database

app = FastAPI(title="Market Analyzer Bot")

db = Database(settings.database_url)
redis_client: Optional[aioredis.Redis] = None
analyzer: Optional[Analyzer] = None


class SubscribeRequest(BaseModel):
    user_id: int
    symbol: str = "BTCUSD"
    interval: str = "15m"
    alert_types: list[str] = []


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
    await db.upsert_user(data.user_id)
    await db.add_subscription(data.user_id, data.symbol, data.interval, data.alert_types)
    return {"status": "subscribed", "user_id": data.user_id}
