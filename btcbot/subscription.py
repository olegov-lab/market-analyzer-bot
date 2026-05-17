from enum import Enum
from typing import Optional

import asyncpg


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    PRO_PLUS = "pro_plus"


TIER_PRICES = {
    "pro": {"stars": 80, "title": "PRO", "label": "PRO (80 ⭐/мес)"},
    "pro_plus": {"stars": 200, "title": "PRO+", "label": "PRO+ (200 ⭐/мес)"},
}

FREE_FEATURES = {
    "dashboard", "chart", "news", "lessons", "game",
    "btc_indicators", "subscribe_basic", "alerts_basic",
}

PRO_FEATURES = FREE_FEATURES | {
    "ask_unlimited", "alerts_pro", "game_unlimited",
    "leaderboard_full", "indicator_history",
}

PRO_PLUS_FEATURES = PRO_FEATURES | {
    "voice_input", "proactive_alerts", "confidence_score",
    "personal_dashboard",
}


async def get_user_tier(db, user_id: int) -> Tier:
    async with db.pool.acquire(timeout=5.0) as conn:
        row = await conn.fetchrow(
            "SELECT tier, trial_until, pro_until, pro_plus_until FROM user_subscriptions WHERE user_id = $1",
            user_id,
        )
        if not row:
            return Tier.FREE
        now = await conn.fetchval("SELECT NOW()")
        if row["pro_plus_until"] and row["pro_plus_until"] > now:
            return Tier.PRO_PLUS
        if row["pro_until"] and row["pro_until"] > now:
            return Tier.PRO
        if row["trial_until"] and row["trial_until"] > now:
            return Tier.PRO
        return Tier.FREE


async def has_feature(db, user_id: int, feature: str) -> bool:
    tier = await get_user_tier(db, user_id)
    if tier == Tier.PRO_PLUS:
        return feature in PRO_PLUS_FEATURES
    if tier == Tier.PRO:
        return feature in PRO_FEATURES
    return feature in FREE_FEATURES


async def activate_trial(db, user_id: int) -> None:
    async with db.pool.acquire(timeout=5.0) as conn:
        await conn.execute("""
            INSERT INTO user_subscriptions (user_id, tier, trial_until)
            VALUES ($1, 'pro', NOW() + INTERVAL '72 hours')
            ON CONFLICT (user_id) DO UPDATE
            SET trial_until = GREATEST(user_subscriptions.trial_until, EXCLUDED.trial_until)
        """, user_id)


async def activate_pro(db, user_id: int, days: int = 30) -> None:
    async with db.pool.acquire(timeout=5.0) as conn:
        await conn.execute("""
            INSERT INTO user_subscriptions (user_id, tier, pro_until)
            VALUES ($1, 'pro', NOW() + ($2 || ' days')::interval)
            ON CONFLICT (user_id) DO UPDATE
            SET tier = 'pro',
                pro_until = GREATEST(
                    COALESCE(user_subscriptions.pro_until, NOW()),
                    NOW() + ($2 || ' days')::interval
                )
        """, user_id, str(days))


async def activate_pro_plus(db, user_id: int, days: int = 30) -> None:
    async with db.pool.acquire(timeout=5.0) as conn:
        await conn.execute("""
            INSERT INTO user_subscriptions (user_id, tier, pro_plus_until)
            VALUES ($1, 'pro_plus', NOW() + ($2 || ' days')::interval)
            ON CONFLICT (user_id) DO UPDATE
            SET tier = 'pro_plus',
                pro_plus_until = GREATEST(
                    COALESCE(user_subscriptions.pro_plus_until, NOW()),
                    NOW() + ($2 || ' days')::interval
                )
        """, user_id, str(days))


async def get_ask_count_today(redis, user_id: int) -> int:
    key = f"ask_count:{user_id}"
    count = await redis.get(key)
    return int(count) if count else 0


async def increment_ask_count(redis, user_id: int) -> int:
    key = f"ask_count:{user_id}"
    count = await redis.incr(key)
    await redis.expire(key, 86400)  # reset daily
    return count


async def get_trade_count_today(redis, user_id: int) -> int:
    key = f"trade_count:{user_id}"
    count = await redis.get(key)
    return int(count) if count else 0


async def increment_trade_count(redis, user_id: int) -> int:
    key = f"trade_count:{user_id}"
    count = await redis.incr(key)
    await redis.expire(key, 86400)
    return count
