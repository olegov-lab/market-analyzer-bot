import json
from datetime import datetime
from typing import Any, Optional

import asyncpg
from loguru import logger


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        await self._init_schema()
        logger.info("Database connected")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            logger.info("Database disconnected")

    async def _init_schema(self) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS prices (
                    time TIMESTAMPTZ NOT NULL,
                    symbol TEXT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION NOT NULL,
                    source TEXT NOT NULL
                )
            """)

            rows = await conn.fetch(
                "SELECT 1 FROM _timescaledb_catalog.hypertable WHERE table_name = 'prices'"
            )
            if not rows:
                await conn.execute(
                    "SELECT create_hypertable('prices', 'time', chunk_time_interval => INTERVAL '1 day')"
                )

            await conn.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS candles_1m
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('1 minute', time) AS bucket,
                    symbol,
                    FIRST(price, time) AS open,
                    MAX(price) AS high,
                    MIN(price) AS low,
                    LAST(price, time) AS close,
                    SUM(volume) AS volume
                FROM prices
                GROUP BY bucket, symbol
                WITH NO DATA
            """)
            try:
                await conn.execute("SELECT add_continuous_aggregate_policy('candles_1m', start_offset => INTERVAL '1 day', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 minute')")
            except Exception:
                pass

            await conn.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS candles_4h
                WITH (timescaledb.continuous) AS
                SELECT
                    time_bucket('4 hours', bucket) AS bucket,
                    symbol,
                    FIRST(open, bucket) AS open,
                    MAX(high) AS high,
                    MIN(low) AS low,
                    LAST(close, bucket) AS close,
                    SUM(volume) AS volume
                FROM candles_1m
                GROUP BY time_bucket('4 hours', bucket), symbol
                WITH NO DATA
            """)
            try:
                await conn.execute("SELECT add_continuous_aggregate_policy('candles_4h', start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour')")
            except Exception:
                pass
            try:
                await conn.execute("CALL refresh_continuous_aggregate('candles_4h', NULL, NULL)")
            except Exception:
                pass
            try:
                await conn.execute("SELECT remove_retention_policy('prices', if_exists => true)")
                await conn.execute("SELECT add_retention_policy('prices', INTERVAL '180 days')")
            except Exception:
                pass

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE,
                    timezone TEXT DEFAULT 'UTC'
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    interval TEXT DEFAULT '15m',
                    alert_types TEXT[] DEFAULT '{}'
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    time TIMESTAMPTZ NOT NULL,
                    horizon TEXT NOT NULL,
                    price_min DOUBLE PRECISION NOT NULL,
                    price_max DOUBLE PRECISION NOT NULL,
                    direction TEXT NOT NULL,
                    confidence DOUBLE PRECISION NOT NULL,
                    meta JSONB DEFAULT '{}'
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    alert_type TEXT NOT NULL,
                    price DOUBLE PRECISION,
                    message TEXT NOT NULL,
                    sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS onchain_metrics (
                    time TIMESTAMPTZ NOT NULL,
                    metric_name TEXT NOT NULL,
                    value DOUBLE PRECISION NOT NULL,
                    source TEXT NOT NULL
                )
            """)

    async def save_price(self, record: Any) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO prices (time, symbol, price, volume, source) VALUES ($1, $2, $3, $4, $5)",
                record.time, record.symbol, record.price, record.volume, record.source,
            )

    async def save_prices_batch(self, records: list[Any]) -> None:
        if not records:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO prices (time, symbol, price, volume, source) VALUES ($1, $2, $3, $4, $5)",
                [(r.time, r.symbol, r.price, r.volume, r.source) for r in records],
            )

    async def get_latest_price(self, symbol: str = "BTCUSD") -> Optional[float]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT price FROM prices WHERE symbol = $1 ORDER BY time DESC LIMIT 1", symbol
            )
            return row["price"] if row else None

    async def save_prediction(self, pred: Any) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO predictions (time, horizon, price_min, price_max, direction, confidence, meta) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                pred.time, pred.horizon, pred.price_min, pred.price_max, pred.direction, pred.confidence, json.dumps(pred.meta),
            )

    async def get_latest_prediction(self) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM predictions ORDER BY time DESC LIMIT 1")

    async def save_onchain_metric(self, metric: Any) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO onchain_metrics (time, metric_name, value, source) VALUES ($1,$2,$3,$4)",
                metric.time, metric.metric_name, metric.value, metric.source,
            )

    async def upsert_user(self, user_id: int, username: Optional[str] = None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = COALESCE($2, users.username)",
                user_id, username,
            )

    async def add_subscription(
        self, user_id: int, symbol: str, interval: str, alert_types: list[str]
    ) -> None:
        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id, alert_types FROM subscriptions WHERE user_id=$1 AND symbol=$2 AND interval=$3",
                user_id, symbol, interval,
            )
            if existing:
                merged = list(set(existing["alert_types"] + alert_types))
                await conn.execute(
                    "UPDATE subscriptions SET alert_types=$1 WHERE id=$2",
                    merged, existing["id"],
                )
            else:
                await conn.execute(
                    "INSERT INTO subscriptions (user_id, symbol, interval, alert_types) VALUES ($1,$2,$3,$4)",
                    user_id, symbol, interval, alert_types,
                )

    async def get_user_subscriptions(self, user_id: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM subscriptions WHERE user_id = $1", user_id
            )

    async def delete_subscription(self, sub_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM subscriptions WHERE id = $1", sub_id)

    async def remove_alert_type(self, sub_id: int, alert_type: str) -> None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT alert_types FROM subscriptions WHERE id=$1", sub_id)
            if not row:
                return
            remaining = [t for t in row["alert_types"] if t != alert_type]
            if remaining:
                await conn.execute("UPDATE subscriptions SET alert_types=$1 WHERE id=$2", remaining, sub_id)
            else:
                await conn.execute("DELETE FROM subscriptions WHERE id=$1", sub_id)

    async def get_prices_since(
        self, symbol: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT time, price, volume FROM prices WHERE symbol = $1 AND time >= $2 ORDER BY time ASC",
                symbol, since,
            )

    async def get_1m_candles_since(
        self, symbol: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT bucket as time, close as price, volume
                FROM candles_1m
                WHERE symbol = $1 AND bucket >= $2
                ORDER BY bucket ASC
            """, symbol, since)

    async def get_4h_candles_since(
        self, symbol: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT bucket, open, high, low, close, volume
                FROM candles_4h
                WHERE symbol = $1 AND bucket >= $2
                ORDER BY bucket ASC
            """, symbol, since)

    async def get_daily_candles_since(
        self, symbol: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT
                    time_bucket('1 day', bucket) AS bucket,
                    LAST(close, bucket) AS close
                FROM candles_1m
                WHERE symbol = $1 AND bucket >= $2
                GROUP BY time_bucket('1 day', bucket), symbol
                HAVING COUNT(*) >= 1
                ORDER BY bucket ASC
            """, symbol, since)

    async def get_active_users(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT user_id, timezone FROM users WHERE is_active = TRUE"
            )

    async def get_users_with_subscriptions(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT u.user_id, u.timezone, unnest(s.alert_types) as alert_type
                FROM users u
                JOIN subscriptions s ON u.user_id = s.user_id
                WHERE u.is_active = TRUE AND s.alert_types != '{}'
            """)

    async def get_onchain_metric_since(
        self, metric_name: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT time, value FROM onchain_metrics WHERE metric_name = $1 AND time >= $2 ORDER BY time ASC",
                metric_name, since,
            )

    async def get_all_onchain_metrics_since(
        self, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT time, metric_name, value FROM onchain_metrics WHERE time >= $1 ORDER BY time ASC",
                since,
            )
