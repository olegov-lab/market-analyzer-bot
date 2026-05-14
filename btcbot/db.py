import json
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import asyncpg
from loguru import logger


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        try:
            self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        except asyncpg.InvalidCatalogNameError:
            dbname = self._parse_dbname()
            logger.warning("Database '{}' not found, creating...", dbname)
            await self._ensure_database(dbname)
            self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        await self._init_schema()
        logger.info("Database connected")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            logger.info("Database disconnected")

    def _parse_dbname(self) -> str:
        parsed = urlparse(self.dsn)
        return parsed.path.lstrip("/") or "postgres"

    async def _ensure_database(self, dbname: str) -> None:
        parsed = urlparse(self.dsn)
        admin_dsn = urlunparse(parsed._replace(path="/postgres"))
        admin = await asyncpg.connect(admin_dsn)
        try:
            exists = await admin.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", dbname
            )
            if not exists:
                await admin.execute(f"CREATE DATABASE {re.sub(r'[^a-zA-Z0-9_]', '', dbname)}")
                logger.info("Created database '{}'", dbname)
        finally:
            await admin.close()
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
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    target_price DOUBLE PRECISION NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'any',
                    triggered BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    triggered_at TIMESTAMPTZ
                )
            """)
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_price_alerts_active
                    ON price_alerts (triggered, target_price)
                    WHERE triggered = FALSE
                """)
            except Exception:
                pass

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

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    tier TEXT NOT NULL DEFAULT 'free',
                    trial_until TIMESTAMPTZ,
                    pro_until TIMESTAMPTZ,
                    pro_plus_until TIMESTAMPTZ,
                    ton_wallet TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            for col, col_def in [
                ("ton_wallet", "TEXT"),
                ("created_at", "TIMESTAMPTZ DEFAULT NOW()"),
                ("updated_at", "TIMESTAMPTZ DEFAULT NOW()"),
            ]:
                try:
                    await conn.execute(f"ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS {col} {col_def}")
                except Exception:
                    pass

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS crypto_payments (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    wallet_address TEXT NOT NULL,
                    chain TEXT NOT NULL DEFAULT 'ton',
                    amount_nano DECIMAL(30,0) NOT NULL,
                    amount_ton DECIMAL(20,9) NOT NULL,
                    tx_hash TEXT,
                    tier TEXT NOT NULL CHECK (tier IN ('pro','pro_plus')),
                    comment TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','paid','expired','failed')),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
            """)

            # --- Game tables ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS game_users (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    balance DOUBLE PRECISION DEFAULT 10000,
                    total_pnl DOUBLE PRECISION DEFAULT 0,
                    total_trades INT DEFAULT 0,
                    winning_trades INT DEFAULT 0,
                    stars BIGINT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            try:
                await conn.execute("ALTER TABLE game_users ADD COLUMN IF NOT EXISTS stars BIGINT DEFAULT 0")
            except Exception:
                pass
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES game_users(user_id) ON DELETE CASCADE,
                    side TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
                    entry_price DOUBLE PRECISION NOT NULL,
                    quantity DOUBLE PRECISION NOT NULL,
                    notional DOUBLE PRECISION NOT NULL,
                    opened_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES game_users(user_id) ON DELETE CASCADE,
                    side TEXT NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL,
                    exit_price DOUBLE PRECISION NOT NULL,
                    quantity DOUBLE PRECISION NOT NULL,
                    pnl DOUBLE PRECISION NOT NULL,
                    pnl_pct DOUBLE PRECISION NOT NULL,
                    opened_at TIMESTAMPTZ NOT NULL,
                    closed_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS leaderboard_mv AS
                SELECT
                    gu.user_id,
                    u.username,
                    gu.balance,
                    gu.total_pnl,
                    gu.total_trades,
                    CASE WHEN gu.total_trades > 0
                        THEN gu.winning_trades::float / gu.total_trades
                        ELSE 0 END AS win_rate,
                    ROW_NUMBER() OVER (ORDER BY gu.total_pnl DESC) AS rank
                FROM game_users gu
                JOIN users u ON gu.user_id = u.user_id
                WHERE gu.total_trades >= 1
                ORDER BY gu.total_pnl DESC
                LIMIT 20
            """)

            # --- Gamification tables ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tournaments (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    starts_at TIMESTAMPTZ NOT NULL,
                    ends_at TIMESTAMPTZ NOT NULL,
                    prize_pool_stars INT NOT NULL DEFAULT 500,
                    status TEXT NOT NULL DEFAULT 'upcoming'
                        CHECK (status IN ('upcoming','active','finished'))
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tournament_entries (
                    tournament_id BIGINT REFERENCES tournaments(id) ON DELETE CASCADE,
                    user_id BIGINT REFERENCES game_users(user_id) ON DELETE CASCADE,
                    start_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    final_pnl DOUBLE PRECISION,
                    pnl_delta DOUBLE PRECISION,
                    rank INT,
                    prize_stars INT DEFAULT 0,
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (tournament_id, user_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id BIGSERIAL PRIMARY KEY,
                    referrer_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    referred_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    bonus_usd DOUBLE PRECISION NOT NULL DEFAULT 5,
                    bonus_credited BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (referrer_id, referred_id)
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

    async def save_onchain_metrics_batch(self, metrics: list[Any]) -> None:
        if not metrics:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO onchain_metrics (time, metric_name, value, source) VALUES ($1,$2,$3,$4)",
                [(m.time, m.metric_name, m.value, m.source) for m in metrics],
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
            rows = await conn.fetch("""
                SELECT bucket as time, close as price, volume
                FROM candles_1m
                WHERE symbol = $1 AND bucket >= $2
                ORDER BY bucket ASC
            """, symbol, since)
            if not rows:
                rows = await conn.fetch("""
                    SELECT time_bucket('1 minute', time) AS time,
                           LAST(price, time) AS price,
                           SUM(volume) AS volume
                    FROM prices
                    WHERE symbol = $1 AND time >= $2
                    GROUP BY time_bucket('1 minute', time), symbol
                    ORDER BY 1 ASC
                """, symbol, since)
            return rows

    async def get_4h_candles_since(
        self, symbol: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT bucket, open, high, low, close, volume
                FROM candles_4h
                WHERE symbol = $1 AND bucket >= $2
                ORDER BY bucket ASC
            """, symbol, since)
            if not rows:
                rows = await conn.fetch("""
                    SELECT
                        time_bucket('4 hours', time) AS bucket,
                        FIRST(price, time) AS open,
                        MAX(price) AS high,
                        MIN(price) AS low,
                        LAST(price, time) AS close,
                        SUM(volume) AS volume
                    FROM prices
                    WHERE symbol = $1 AND time >= $2
                    GROUP BY bucket, symbol
                    ORDER BY bucket ASC
                """, symbol, since)
            return rows

    async def get_daily_candles_since(
        self, symbol: str, since: datetime
    ) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    time_bucket('1 day', bucket) AS bucket,
                    LAST(close, bucket) AS close
                FROM candles_1m
                WHERE symbol = $1 AND bucket >= $2
                GROUP BY time_bucket('1 day', bucket), symbol
                HAVING COUNT(*) >= 1
                ORDER BY bucket ASC
            """, symbol, since)
            if not rows:
                rows = await conn.fetch("""
                    SELECT
                        time_bucket('1 day', time) AS bucket,
                        LAST(price, time) AS close
                    FROM prices
                    WHERE symbol = $1 AND time >= $2
                    GROUP BY bucket, symbol
                    ORDER BY bucket ASC
                """, symbol, since)
            return rows

    async def get_hourly_candles_since(self, symbol: str, since: datetime) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    time_bucket('1 hour', bucket) AS bucket,
                    FIRST(open, bucket) AS open,
                    MAX(high) AS high,
                    MIN(low) AS low,
                    LAST(close, bucket) AS close,
                    SUM(volume) AS volume
                FROM candles_1m
                WHERE symbol = $1 AND bucket >= $2
                GROUP BY time_bucket('1 hour', bucket), symbol
                HAVING COUNT(*) >= 1
                ORDER BY bucket ASC
            """, symbol, since)

            # Fallback: aggregate from raw prices if continuous aggregates are empty
            if not rows:
                rows = await conn.fetch("""
                    SELECT
                        time_bucket('1 hour', time) AS bucket,
                        FIRST(price, time) AS open,
                        MAX(price) AS high,
                        MIN(price) AS low,
                        LAST(price, time) AS close,
                        SUM(volume) AS volume
                    FROM prices
                    WHERE symbol = $1 AND time >= $2
                    GROUP BY bucket, symbol
                    ORDER BY bucket ASC
                """, symbol, since)

            return rows

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

    async def add_price_alert(self, user_id: int, target_price: float, direction: str = "any") -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO price_alerts (user_id, target_price, direction) VALUES ($1,$2,$3) RETURNING id",
                user_id, target_price, direction,
            )
            return row["id"]

    async def get_user_price_alerts(self, user_id: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM price_alerts WHERE user_id = $1 ORDER BY created_at DESC",
                user_id,
            )

    async def delete_price_alert(self, alert_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM price_alerts WHERE id = $1", alert_id)

    async def get_active_price_alerts(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM price_alerts WHERE triggered = FALSE ORDER BY target_price ASC"
            )

    async def mark_price_alert_triggered(self, alert_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE price_alerts SET triggered = TRUE, triggered_at = NOW() WHERE id = $1",
                alert_id,
            )

    async def get_candles(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[dict]:
        bucket_map = {
            "15m": "15 minutes",
            "1h": "1 hour",
            "4h": "4 hours",
            "1d": "1 day",
            "1w": "1 week",
        }
        interval = bucket_map.get(timeframe)
        if not interval:
            return []

        async with self.pool.acquire() as conn:
            if timeframe == "4h":
                rows = await conn.fetch("""
                    SELECT bucket, open, high, low, close, volume
                    FROM candles_4h
                    WHERE symbol = $1
                    ORDER BY bucket DESC
                    LIMIT $2
                """, symbol, limit)
            else:
                rows = await conn.fetch(f"""
                    SELECT
                        time_bucket('{interval}'::interval, bucket) AS bucket,
                        FIRST(open, bucket) AS open,
                        MAX(high) AS high,
                        MIN(low) AS low,
                        LAST(close, bucket) AS close,
                        SUM(volume) AS volume
                    FROM candles_1m
                    WHERE symbol = $1
                    GROUP BY time_bucket('{interval}'::interval, bucket), symbol
                    ORDER BY bucket DESC
                    LIMIT $2
                """, symbol, limit)

            # Fallback: aggregate from raw prices if continuous aggregates are empty
            if not rows:
                rows = await conn.fetch(f"""
                    SELECT
                        time_bucket('{interval}'::interval, time) AS bucket,
                        FIRST(price, time) AS open,
                        MAX(price) AS high,
                        MIN(price) AS low,
                        LAST(price, time) AS close,
                        SUM(volume) AS volume
                    FROM prices
                    WHERE symbol = $1
                    GROUP BY bucket, symbol
                    ORDER BY bucket DESC
                    LIMIT $2
                """, symbol, limit)

            return [
                {
                    "time": int(r["bucket"].timestamp()),
                    "open": r["open"],
                    "high": r["high"],
                    "low": r["low"],
                    "close": r["close"],
                    "volume": r["volume"],
                }
                for r in reversed(rows)
            ]

    # ─── Game methods ─────────────────────────────────────────────────

    async def get_or_create_game_user(self, user_id: int) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
                user_id, str(user_id),
            )
            row = await conn.fetchrow("SELECT * FROM game_users WHERE user_id = $1", user_id)
            if not row:
                row = await conn.fetchrow(
                    "INSERT INTO game_users (user_id, balance) VALUES ($1, 10000) RETURNING *",
                    user_id,
                )
            return row

    async def open_position(self, user_id: int, side: str, quantity: float, entry_price: float, notional: float) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE game_users SET balance = balance - $1, updated_at = NOW() WHERE user_id = $2",
                    notional, user_id,
                )
                row = await conn.fetchrow(
                    "INSERT INTO positions (user_id, side, entry_price, quantity, notional) VALUES ($1,$2,$3,$4,$5) RETURNING *",
                    user_id, side, entry_price, quantity, notional,
                )
            return row

    async def close_position(self, user_id: int, position_id: int, exit_price: float, fee_pct: float = 0.001) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            pos = await conn.fetchrow("SELECT * FROM positions WHERE id = $1 AND user_id = $2", position_id, user_id)
            if not pos:
                return None
            fee = pos["notional"] * fee_pct * 2  # entry + exit fee
            if pos["side"] == "LONG":
                pnl = (exit_price - pos["entry_price"]) * pos["quantity"] - fee
            else:
                pnl = (pos["entry_price"] - exit_price) * pos["quantity"] - fee
            pnl_pct = (pnl / pos["notional"]) * 100
            async with conn.transaction():
                await conn.execute("DELETE FROM positions WHERE id = $1", position_id)
                await conn.execute(
                    "UPDATE game_users SET balance = balance + $1 + $2, total_pnl = total_pnl + $1, total_trades = total_trades + 1, winning_trades = winning_trades + CASE WHEN $1 > 0 THEN 1 ELSE 0 END, updated_at = NOW() WHERE user_id = $3",
                    pnl, pos["notional"], user_id,
                )
                row = await conn.fetchrow(
                    "INSERT INTO trades (user_id, side, entry_price, exit_price, quantity, pnl, pnl_pct, opened_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
                    user_id, pos["side"], pos["entry_price"], exit_price, pos["quantity"], pnl, pnl_pct, pos["opened_at"],
                )
            return row

    async def get_game_user(self, user_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM game_users WHERE user_id = $1", user_id)

    async def get_positions(self, user_id: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM positions WHERE user_id = $1 ORDER BY opened_at DESC", user_id)

    async def get_trades(self, user_id: int, limit: int = 20, offset: int = 0) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM trades WHERE user_id = $1 ORDER BY closed_at DESC LIMIT $2 OFFSET $3",
                user_id, limit, offset,
            )

    async def refresh_leaderboard(self) -> None:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute("REFRESH MATERIALIZED VIEW leaderboard_mv")
            except Exception:
                pass

    async def get_leaderboard(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM leaderboard_mv ORDER BY rank")

    # ─── Tournament methods ─────────────────────────────────────────

    async def create_tournament(self, name: str, starts_at, ends_at, prize_pool: int = 500) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "INSERT INTO tournaments (name, starts_at, ends_at, prize_pool_stars, status) VALUES ($1,$2,$3,$4,'upcoming') RETURNING *",
                name, starts_at, ends_at, prize_pool,
            )

    async def get_active_tournament(self) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM tournaments WHERE status = 'active' ORDER BY ends_at ASC LIMIT 1"
            )

    async def get_tournaments(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM tournaments ORDER BY starts_at DESC LIMIT 10"
            )

    async def get_tournament(self, tournament_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM tournaments WHERE id = $1", tournament_id)

    async def join_tournament(self, tournament_id: int, user_id: int, current_pnl: float) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "INSERT INTO tournament_entries (tournament_id, user_id, start_pnl) VALUES ($1,$2,$3) "
                "ON CONFLICT (tournament_id, user_id) DO NOTHING RETURNING *",
                tournament_id, user_id, current_pnl,
            )

    async def get_tournament_entries(self, tournament_id: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT te.*, u.username FROM tournament_entries te "
                "JOIN users u ON te.user_id = u.user_id "
                "WHERE te.tournament_id = $1 ORDER BY te.start_pnl DESC",
                tournament_id,
            )

    async def get_tournament_entry(self, tournament_id: int, user_id: int) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM tournament_entries WHERE tournament_id = $1 AND user_id = $2",
                tournament_id, user_id,
            )

    async def update_tournament_rankings(self, tournament_id: int) -> None:
        async with self.pool.acquire() as conn:
            entries = await conn.fetch(
                "SELECT te.user_id, gu.total_pnl - te.start_pnl AS pnl_delta "
                "FROM tournament_entries te JOIN game_users gu ON te.user_id = gu.user_id "
                "WHERE te.tournament_id = $1 ORDER BY pnl_delta DESC",
                tournament_id,
            )
            prizes = [250, 150, 75, 25]
            for i, entry in enumerate(entries):
                prize = prizes[i] if i < len(prizes) else 0
                await conn.execute(
                    "UPDATE tournament_entries SET final_pnl = (SELECT total_pnl FROM game_users WHERE user_id=$1), "
                    "pnl_delta = $2, rank = $3, prize_stars = $4 WHERE tournament_id = $5 AND user_id = $1",
                    entry["user_id"], float(entry["pnl_delta"]), i + 1, prize, tournament_id,
                )
                if prize > 0:
                    await conn.execute(
                        "UPDATE game_users SET stars = stars + $1 WHERE user_id = $2",
                        prize, entry["user_id"],
                    )
            await conn.execute("UPDATE tournaments SET status = 'finished' WHERE id = $1", tournament_id)

    # ─── Referral methods ───────────────────────────────────────────

    async def create_referral(self, referrer_id: int, referred_id: int, bonus_usd: float = 5.0) -> bool:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, bonus_usd) VALUES ($1,$2,$3) "
                    "ON CONFLICT (referrer_id, referred_id) DO NOTHING",
                    referrer_id, referred_id, bonus_usd,
                )
                return True
            except Exception:
                return False

    async def credit_referral_bonus(self, referral_id: int) -> None:
        async with self.pool.acquire() as conn:
            ref = await conn.fetchrow("SELECT referrer_id, bonus_usd FROM referrals WHERE id = $1 AND NOT bonus_credited", referral_id)
            if ref:
                await conn.execute("UPDATE game_users SET balance = balance + $1, updated_at = NOW() WHERE user_id = $2",
                                   ref["bonus_usd"], ref["referrer_id"])
                await conn.execute("UPDATE referrals SET bonus_credited = TRUE WHERE id = $1", referral_id)

    async def get_referral_stats(self, referrer_id: int) -> dict:
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", referrer_id)
            total_bonus = await conn.fetchval("SELECT COALESCE(SUM(bonus_usd), 0) FROM referrals WHERE referrer_id = $1 AND bonus_credited", referrer_id)
            rows = await conn.fetch(
                "SELECT r.id, r.referred_id, u.username, r.bonus_usd, r.bonus_credited, r.created_at "
                "FROM referrals r JOIN users u ON r.referred_id = u.user_id "
                "WHERE r.referrer_id = $1 ORDER BY r.created_at DESC LIMIT 20",
                referrer_id,
            )
            return {"count": count or 0, "total_bonus": float(total_bonus or 0), "referrals": [dict(r) for r in rows]}

    async def add_stars(self, user_id: int, amount: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE game_users SET stars = stars + $1 WHERE user_id = $2", amount, user_id)
