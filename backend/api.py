import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
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
from btcbot.game import GameEngine
from btcbot.lessons import LESSONS
from btcbot.news import NEWS_CACHE_TTL, build_sentiment_summary, fetch_news
from btcbot.subscription import get_user_tier
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
game_engine: Optional[GameEngine] = None

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
    global redis_client, analyzer, fear_greed, game_engine
    await db.connect()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    analyzer = Analyzer(db, redis_client)
    fear_greed = FearGreedIndex(redis_client)
    game_engine = GameEngine(db)
    asyncio.create_task(analyzer.warmup_cache())
    asyncio.create_task(_warmup_timothy_cache())
    asyncio.create_task(_warmup_summary_cache())


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

async def _fast_or_none(coro, timeout=2.0):
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        return None


@app.get("/miniapp/dashboard")
@limiter.limit("30/minute")
async def miniapp_dashboard(request: Request):
    user_id = await _get_user_id(request)
    price, indicators, pred, fng, vol = await safe_gather(
        db.get_latest_price("BTCUSD"),
        _fast_or_none(analyzer.compute_indicators(), 2.0),
        _fast_or_none(analyzer.predict(), 2.0),
        _fast_or_none(fear_greed.fetch(), 1.5),
        _fast_or_none(analyzer.compute_volatility(), 2.0),
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
    consensus = await _fast_or_none(analyzer.compute_consensus(), 2.0)
    summary = None
    if redis_client:
        try:
            cached = await redis_client.get("summary:indicators")
            if cached:
                summary = json.loads(cached)
        except Exception:
            pass
    return {
        "price": price,
        "indicators": indicators.model_dump() if indicators else None,
        "prediction_summary": prediction_summary,
        "fear_greed": fng,
        "volatility": vol_data,
        "consensus": consensus,
        "summary": summary,
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


@app.get("/miniapp/consensus")
@limiter.limit("30/minute")
async def miniapp_consensus(request: Request):
    user_id = await _get_user_id(request)
    return await analyzer.compute_consensus()


@app.get("/miniapp/summary")
@limiter.limit("10/minute")
async def miniapp_summary(request: Request):
    user_id = await _get_user_id(request)
    try:
        from btcbot.summarizer import summarize_indicators
        price, indicators, fng = await safe_gather(
            db.get_latest_price("BTCUSD"),
            analyzer.compute_indicators(),
            fear_greed.fetch(),
            log_prefix="summary",
        )
        onchain = await analyzer._get_onchain_df(datetime.now(timezone.utc) - timedelta(days=30))
        onchain_dict = None
        if onchain is not None and not onchain.empty:
            onchain_dict = {}
            for col in ("mvrv_z", "sopr", "nupl"):
                if col in onchain.columns:
                    v = onchain.iloc[-1].get(col)
                    onchain_dict[col] = round(float(v), 2) if v is not None and v == v else None
        return await summarize_indicators(db, redis_client, price, indicators, fng, onchain_dict)
    except Exception as e:
        logger.warning("miniapp_summary failed: {}", e)
        raise HTTPException(503, "Summary unavailable")


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


@app.get("/miniapp/subscription/status")
@limiter.limit("20/minute")
async def miniapp_subscription_status(request: Request):
    user_id = await _get_user_id(request)
    tier = await get_user_tier(db, user_id)
    tier_str = tier.value
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT trial_until, pro_until, pro_plus_until FROM user_subscriptions WHERE user_id = $1",
            user_id,
        )
    result = {"tier": tier_str}
    if row:
        if row["trial_until"]:
            result["trial_until"] = row["trial_until"].strftime("%d.%m.%Y %H:%M UTC")
        if row["pro_until"]:
            result["pro_until"] = row["pro_until"].strftime("%d.%m.%Y %H:%M UTC")
        if row["pro_plus_until"]:
            result["pro_plus_until"] = row["pro_plus_until"].strftime("%d.%m.%Y %H:%M UTC")
    return result


# ─── Crypto / TON Payment ──────────────────────────────────────────

@app.get("/crypto/wallet/status")
@limiter.limit("20/minute")
async def crypto_wallet_status(request: Request):
    user_id = await _get_user_id(request)
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ton_wallet, updated_at FROM user_subscriptions WHERE user_id = $1",
            user_id,
        )
    if row and row["ton_wallet"]:
        return {"wallet_address": row["ton_wallet"], "linked": True}
    return {"wallet_address": None, "linked": False}


@app.post("/crypto/wallet/link")
@limiter.limit("10/minute")
async def crypto_wallet_link(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    wallet = (body.get("wallet_address") or "").strip()
    if not wallet or len(wallet) < 32:
        raise HTTPException(400, "Invalid TON wallet address")
    async with db.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_subscriptions (user_id, ton_wallet) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO UPDATE SET ton_wallet = $2, updated_at = NOW()",
            user_id, wallet,
        )
    return {"status": "linked", "wallet_address": wallet}


@app.post("/crypto/payment/create")
@limiter.limit("10/minute")
async def crypto_payment_create(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    tier = (body.get("tier") or "").lower()
    wallet = (body.get("wallet_address") or "").strip()

    if tier not in ("pro", "pro_plus"):
        raise HTTPException(400, "Invalid tier")
    if not settings.ton_recipient_wallet:
        raise HTTPException(503, "TON payments not configured")

    amount_ton = settings.ton_pro_plus_price_ton if tier == "pro_plus" else settings.ton_pro_price_ton
    from btcbot.crypto import ton_to_nano
    amount_nano = ton_to_nano(amount_ton)
    comment = f"btcmon_{tier}_{user_id}"

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO crypto_payments (user_id, wallet_address, amount_nano, amount_ton, tier, comment, status) "
            "VALUES ($1,$2,$3,$4,$5,$6,'pending') RETURNING id",
            user_id, wallet, amount_nano, amount_ton, tier, comment,
        )

    return {
        "payment_id": row["id"],
        "amount_ton": amount_ton,
        "amount_nano": amount_nano,
        "recipient_wallet": settings.ton_recipient_wallet,
        "comment": comment,
        "ton_uri": f"ton://transfer/{settings.ton_recipient_wallet}?amount={amount_nano}&text={comment}",
    }


@app.get("/crypto/payment/{payment_id}")
@limiter.limit("30/minute")
async def crypto_payment_status(request: Request, payment_id: int):
    user_id = await _get_user_id(request)
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, tier, amount_ton, tx_hash, paid_at, comment "
            "FROM crypto_payments WHERE id = $1 AND user_id = $2",
            payment_id, user_id,
        )
    if not row:
        raise HTTPException(404, "Payment not found")
    return {
        "payment_id": row["id"],
        "status": row["status"],
        "tier": row["tier"],
        "amount_ton": float(row["amount_ton"]),
        "tx_hash": row["tx_hash"],
        "paid_at": row["paid_at"].isoformat() if row["paid_at"] else None,
    }


@app.post("/crypto/payment/{payment_id}/verify")
@limiter.limit("10/minute")
async def crypto_payment_verify(request: Request, payment_id: int):
    user_id = await _get_user_id(request)
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    tx_hash = (body.get("tx_hash") or "").strip()

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, amount_nano, amount_ton, tier, comment, status, created_at "
            "FROM crypto_payments WHERE id = $1 AND user_id = $2",
            payment_id, user_id,
        )
    if not row:
        raise HTTPException(404, "Payment not found")
    if row["status"] == "paid":
        return {"status": "paid", "tier": row["tier"]}

    if not settings.ton_recipient_wallet:
        raise HTTPException(503, "TON payments not configured")

    from btcbot.crypto import TONVerifier
    verifier = TONVerifier(settings.toncenter_api_url)

    verified = False
    found_tx_hash = tx_hash

    if tx_hash:
        verified = await verifier.verify_transaction(tx_hash, settings.ton_recipient_wallet, int(row["amount_nano"]))
    else:
        from datetime import timedelta
        result = await verifier.find_incoming_payment(
            settings.ton_recipient_wallet,
            int(row["amount_nano"]),
            row["comment"],
            row["created_at"] - timedelta(minutes=5),
        )
        if result:
            verified = True
            found_tx_hash = result["tx_hash"]

    if verified:
        from btcbot.subscription import activate_pro, activate_pro_plus
        if row["tier"] == "pro_plus":
            await activate_pro_plus(db, user_id)
        else:
            await activate_pro(db, user_id)

        async with db.pool.acquire() as conn2:
            await conn2.execute(
                "UPDATE crypto_payments SET status='paid', tx_hash=$1, paid_at=NOW() WHERE id=$2",
                found_tx_hash, payment_id,
            )
        return {"status": "paid", "tier": row["tier"], "tx_hash": found_tx_hash}

    return {"status": "pending"}


# ─── Async AI task store (polling-based) ──────────────────────────

async def _fetch_timothy_analysis(price: Optional[float], indicators) -> str:
    """Call OpenCode agent for Timothy Peterson-style analysis with current market data."""
    system_prompt = (
        "You are Timothy Peterson, a renowned Bitcoin analyst and author of the paper "
        "'Metcalfe's Law as a Model for Bitcoin's Value'. You are known for the Lowest Price "
        "Forward (LPF) indicator and modeling BTC price using network effects. "
        "Your analysis style: data-driven, quantitative, skeptical of hype, focused on long-term "
        "trends, Metcalfe's Law, hash rate, and adoption curves. Answer in Russian, "
        "be concise (300-400 words). Use ONLY the real-time data provided in the prompt. "
        "Do NOT invent prices or dates — reference only what is given."
    )
    ctx_parts = []
    if price:
        ctx_parts.append(f"Текущая цена BTC: ${price:,.0f}")
    if indicators:
        if indicators.rsi is not None:
            ctx_parts.append(f"RSI(14): {indicators.rsi:.1f}")
        if indicators.ma_50 is not None and indicators.ma_200 is not None:
            ctx_parts.append(f"MA50: ${indicators.ma_50:,.0f}, MA200: ${indicators.ma_200:,.0f}")
    ctx = "\n".join(ctx_parts)
    prompt = (
        "Give a brief Bitcoin market analysis in your signature Timothy Peterson style.\n\n"
        f"REAL-TIME DATA (use these exact numbers, do not fabricate):\n{ctx}\n\n"
        "Include your view on current valuation relative to Metcalfe's Law, "
        "key support/resistance levels based on the MA values above, and near-term outlook. "
        "Write in Russian, 300-400 words."
    )
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
    msg = resp.choices[0].message
    text = msg.content or ""
    reasoning = getattr(msg, "reasoning_content", None) or ""
    return text or reasoning or "[empty response]"


async def _warmup_timothy_cache():
    """Pre-fill Timothy news cache at startup so first user request is instant."""
    cache_key = "news:timothy"
    if redis_client and await redis_client.exists(cache_key):
        return
    try:
        price, indicators = await safe_gather(
            db.get_latest_price("BTCUSD"),
            analyzer.compute_indicators(),
            log_prefix="timothy_warmup",
        )
        text = await _fetch_timothy_analysis(price, indicators)
        result = {"text": text, "source": "Timothy Peterson via AI"}
        if redis_client:
            await redis_client.setex(cache_key, 3600, json.dumps(result, ensure_ascii=False))
        logger.info("Timothy news cache warmed up")
    except Exception as e:
        logger.warning(f"Timothy cache warmup skipped: {e}")


async def _warmup_summary_cache():
    await asyncio.sleep(5)
    cache_key = "summary:indicators"
    if redis_client and await redis_client.exists(cache_key):
        return
    try:
        from btcbot.summarizer import summarize_indicators
        price, indicators, fng = await safe_gather(
            db.get_latest_price("BTCUSD"),
            analyzer.compute_indicators(),
            fear_greed.fetch(),
            log_prefix="summary_warmup",
        )
        await summarize_indicators(db, redis_client, price, indicators, fng, None)
        logger.info("Summary cache warmed up")
    except Exception as e:
        logger.warning(f"Summary cache warmup skipped: {e}")


_ask_task_counter = 0

ASK_TASK_TTL = 600


async def _run_ask_task(task_id: str, question: str, user_id: int):
    task_key = f"btc:ask:{task_id}"
    if redis_client:
        await redis_client.setex(task_key, ASK_TASK_TTL, json.dumps({"status": "running", "result": None}))
    try:
        ctx_parts = [f"Сегодня {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}"]
        price = await db.get_latest_price("BTCUSD")
        if price:
            ctx_parts.append(f"Цена BTC: ${price:,.0f}")
        if redis_client:
            try:
                cached_ind = await redis_client.get("indicators:BTCUSD")
                if cached_ind:
                    ind = json.loads(cached_ind)
                    if ind.get("rsi") is not None:
                        ctx_parts.append(f"RSI(14): {ind['rsi']:.1f}")
                    if ind.get("ma_50") is not None:
                        ctx_parts.append(f"MA50: ${ind['ma_50']:,.0f}")
                    if ind.get("ma_200") is not None:
                        ctx_parts.append(f"MA200: ${ind['ma_200']:,.0f}")
            except Exception:
                pass
        ctx = " | ".join(ctx_parts)
        result = await ask_agent(
            "marketbrain",
            f"Контекст рынка: {ctx}\n\nВопрос пользователя: {question}\n\nОтветь на русском языке, используя контекст если нужно.",
            temperature=0.7,
        )
        if redis_client:
            if result and "[Agent error:" not in result:
                await redis_client.setex(task_key, ASK_TASK_TTL, json.dumps({"status": "done", "result": result}, ensure_ascii=False))
            else:
                await redis_client.setex(task_key, ASK_TASK_TTL, json.dumps({"status": "error", "result": "AI agent temporarily unavailable"}, ensure_ascii=False))
    except Exception as e:
        if redis_client:
            await redis_client.setex(task_key, ASK_TASK_TTL, json.dumps({"status": "error", "result": str(e)}, ensure_ascii=False))


@app.post("/miniapp/ask")
@limiter.limit("10/minute")
async def miniapp_ask(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    global _ask_task_counter
    _ask_task_counter += 1
    task_id = f"ask_{_ask_task_counter}_{int(time.time())}"
    if redis_client:
        await redis_client.setex(f"btc:ask:{task_id}", ASK_TASK_TTL, json.dumps({"status": "pending", "result": None}))
    asyncio.create_task(_run_ask_task(task_id, question, user_id))
    return {"task_id": task_id}


@app.get("/miniapp/ask/{task_id}")
@limiter.limit("120/minute")
async def miniapp_ask_status(request: Request, task_id: str):
    user_id = await _get_user_id(request)
    task_key = f"btc:ask:{task_id}"
    if redis_client:
        data = await redis_client.get(task_key)
        if data:
            return json.loads(data)
    raise HTTPException(404, "Task not found")


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


@app.get("/miniapp/metcalfe")
@limiter.limit("20/minute")
async def miniapp_metcalfe(request: Request):
    user_id = await _get_user_id(request)
    if not redis_client or not db:
        raise HTTPException(503, "Service not ready")
    from btcbot.metcalfe import MetcalfeEngine
    engine = MetcalfeEngine(db, redis_client)
    result = await engine.compute()
    if not result:
        raise HTTPException(503, "Not enough data for Metcalfe corridor (need 30+ days)")
    return result


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
        "and a short-term outlook. Use ONLY the real-time data provided in the prompt. "
        "Do NOT invent prices or dates — reference only what is given."
    )
    # Fetch current market context for accurate analysis
    price = indicators = None
    try:
        price, indicators = await safe_gather(
            db.get_latest_price("BTCUSD"),
            analyzer.compute_indicators(),
        )
    except Exception:
        pass

    ctx_parts = []
    if price:
        ctx_parts.append(f"Текущая цена BTC: ${price:,.0f}")
    if indicators:
        if indicators.rsi is not None:
            ctx_parts.append(f"RSI(14): {indicators.rsi:.1f}")
        if indicators.ma_50 is not None and indicators.ma_200 is not None:
            ctx_parts.append(f"MA50: ${indicators.ma_50:,.0f}, MA200: ${indicators.ma_200:,.0f}")
    ctx = "\n".join(ctx_parts)
    prompt = (
        "Give a brief Bitcoin market analysis in your signature Timothy Peterson style.\n\n"
        f"REAL-TIME DATA (use these exact numbers, do not fabricate):\n{ctx}\n\n"
        "Include your view on current valuation relative to Metcalfe's Law, "
        "key support/resistance levels based on the MA values above, and near-term outlook. "
        "Write in Russian, 300-400 words."
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
        msg = resp.choices[0].message
        text = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or ""
        text = text or reasoning or "[empty response]"
        result = {"text": text, "source": "Timothy Peterson via AI"}
    except Exception as e:
        logger.error(f"Timothy news agent error: {e}")
        result = {"text": f"Не удалось получить анализ. Попробуйте позже.", "source": "error"}

    if redis_client:
        await redis_client.setex(cache_key, 3600, json.dumps(result, ensure_ascii=False))
    return result


# ─── Game (Trading Simulator) ─────────────────────────────────────

@app.get("/miniapp/game/state")
@limiter.limit("30/minute")
async def game_state(request: Request):
    user_id = await _get_user_id(request)
    return await game_engine.get_portfolio(user_id)


@app.post("/miniapp/game/buy")
@limiter.limit("10/minute")
async def game_buy(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    usdt_amount = float(body.get("usdt_amount", 0))
    try:
        result = await game_engine.buy(user_id, usdt_amount)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/miniapp/game/sell")
@limiter.limit("10/minute")
async def game_sell(request: Request):
    user_id = await _get_user_id(request)
    try:
        result = await game_engine.sell(user_id)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/miniapp/game/history")
@limiter.limit("30/minute")
async def game_history(request: Request, limit: int = 20, offset: int = 0):
    user_id = await _get_user_id(request)
    return await game_engine.get_history(user_id, limit, offset)


@app.get("/miniapp/game/leaderboard")
@limiter.limit("30/minute")
async def game_leaderboard(request: Request):
    return await game_engine.get_leaderboard()


# ─── Gamification endpoints ─────────────────────────────────────────

@app.get("/miniapp/game/league")
@limiter.limit("30/minute")
async def game_league(request: Request):
    user_id = await _get_user_id(request)
    user = await game_engine.db.get_or_create_game_user(user_id)
    return game_engine.compute_league(user["total_pnl"] or 0)


@app.get("/miniapp/game/tournament")
@limiter.limit("30/minute")
async def game_tournament(request: Request):
    user_id = await _get_user_id(request)
    return await game_engine.get_tournament_state(user_id)


@app.post("/miniapp/game/tournament/{tournament_id}/join")
@limiter.limit("10/minute")
async def game_tournament_join(request: Request, tournament_id: int):
    user_id = await _get_user_id(request)
    return await game_engine.join_tournament(tournament_id, user_id)


@app.get("/miniapp/game/pnl-card")
@limiter.limit("30/minute")
async def game_pnl_card(request: Request):
    user_id = await _get_user_id(request)
    return await game_engine.get_pnl_card_data(user_id)


@app.get("/miniapp/referral/stats")
@limiter.limit("30/minute")
async def referral_stats(request: Request):
    user_id = await _get_user_id(request)
    return await game_engine.get_referral_info(user_id)


@app.post("/miniapp/referral")
@limiter.limit("10/minute")
async def referral_create(request: Request):
    user_id = await _get_user_id(request)
    body = await request.json()
    referred_id = body.get("referred_id")
    if not referred_id:
        raise HTTPException(400, "referred_id required")
    return await game_engine.add_referral(user_id, referred_id)


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
