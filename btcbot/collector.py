import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from loguru import logger

from btcbot.config import settings
from btcbot.db import Database
from btcbot.models import OnchainMetric, PriceRecord

BITVIEW_BASE = "https://bitview.space/api/series"
BYBIT_BASE = "https://api.bybit.com/v5/market"
OKX_BASE = "https://www.okx.com/api/v5/public"

BITVIEW_METRICS = {
    "mvrv": "mvrv_z_score",
    "sopr_24h": "sopr_realized",
    "nupl": "nupl",
    "puell_multiple": "puell_multiple",
    "rhodl_ratio": "rhodl_ratio",
    "sth_sopr_24h": "sthsopr",
    "reserve_risk": "reserve_risk",
}


VOLUME_WINDOW = 3600


class VolumeTracker:
    def __init__(self, redis_client: Any, window: int = VOLUME_WINDOW) -> None:
        self.redis = redis_client
        self.window = window
        self._volumes: list[tuple[datetime, float]] = []

    def add(self, volume: float, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window)
        self._volumes.append((now, volume))
        self._volumes = [(t, v) for t, v in self._volumes if t > cutoff]

    async def publish_stats(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window)
        recent = [v for t, v in self._volumes if t > cutoff]
        if not recent:
            return
        avg = sum(recent) / len(recent)
        current_sum = sum(recent[-60:]) if len(recent) >= 60 else sum(recent)
        await self.redis.set("btc:volume:avg", str(avg))
        await self.redis.set("btc:volume:current", str(current_sum))


class PriceBuffer:

    async def add(self, record: Any) -> None:
        async with self._lock:
            self._buf.append(record)
            if len(self._buf) >= self.max_size:
                await self._flush()

    async def _flush(self) -> None:
        if not self._buf:
            return
        batch = self._buf[:]
        self._buf.clear()
        try:
            await self.db.save_prices_batch(batch)
        except Exception as e:
            logger.error("Batch insert failed: {}", e)

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            async with self._lock:
                await self._flush()


class PriceCollector:
    def __init__(self, db: Database, redis_client: Any, s: Any) -> None:
        self.db = db
        self.redis = redis_client
        self.settings = s
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._buffer = PriceBuffer(db)
        self._volume_tracker = VolumeTracker(redis_client)

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession()
        await asyncio.gather(
            self._binance_ws_loop(),
            self._coingecko_loop(),
            self._bitview_loop(),
            self._futures_loop(),
            self._buffer.flush_loop(),
            self._volume_stats_loop(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()

    async def _volume_stats_loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)
            await self._volume_tracker.publish_stats(datetime.now(timezone.utc))

    async def _binance_ws_loop(self) -> None:
        url = f"{self.settings.binance_ws_url}/btcusdt@aggTrade"
        while self._running:
            try:
                async with self._session.ws_connect(url) as ws:
                        logger.info("Binance WebSocket connected")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                price = float(data["p"])
                                volume = float(data["q"])
                                now = datetime.now(timezone.utc)
                                record = PriceRecord(
                                    time=now, symbol="BTCUSD",
                                    price=price, volume=volume, source="binance",
                                )
                                await self._buffer.add(record)
                                self._volume_tracker.add(volume, now)
                                await self.redis.set("btc:price", str(price))
                                await self.redis.publish(
                                    "btc:price:live",
                                    json.dumps({
                                        "price": price,
                                        "volume": volume,
                                        "time": now.isoformat(),
                                    }),
                                )
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error("Binance WS error: {}", msg)
                                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Binance WS reconnect in 5s: {}", e)
                await asyncio.sleep(5)

    async def _coingecko_loop(self) -> None:
        url = (
            f"{self.settings.coingecko_api_url}/simple/price"
            "?ids=bitcoin&vs_currencies=usd&include_24hr_vol=true"
        )
        while self._running:
            try:
                async with self._session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = data["bitcoin"]["usd"]
                        volume = data["bitcoin"].get("usd_24h_vol", 0)
                        now = datetime.now(timezone.utc)
                        record = PriceRecord(
                            time=now, symbol="BTCUSD",
                            price=price, volume=volume, source="coingecko",
                        )
                        await self._buffer.add(record)
                await asyncio.sleep(60)
            except Exception as e:
                logger.error("CoinGecko error: {}", e)
                await asyncio.sleep(30)

    async def _bitview_loop(self) -> None:
        while self._running:
            genesis = datetime(2009, 1, 3, tzinfo=timezone.utc)
            today = datetime.now(timezone.utc).date()
            target_idx = (today - genesis.date()).days

            for series_name, db_name in BITVIEW_METRICS.items():
                try:
                    url = f"{BITVIEW_BASE}/{series_name}/day"
                    async with self._session.get(url) as resp:
                        if resp.status == 200:
                            body = await resp.json()
                            data_arr = body.get("data", [])
                            if target_idx < len(data_arr) and data_arr[target_idx] is not None:
                                record = OnchainMetric(
                                    time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
                                    metric_name=db_name,
                                    value=float(data_arr[target_idx]),
                                    source="bitview",
                                )
                                await self.db.save_onchain_metric(record)
                                logger.info("Bitview {}: {}", db_name, record.value)
                            else:
                                # fallback to last non-null
                                for i in range(min(target_idx, len(data_arr) - 1), 0, -1):
                                    if data_arr[i] is not None:
                                        record = OnchainMetric(
                                            time=datetime.combine(genesis + timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc),
                                            metric_name=db_name,
                                            value=float(data_arr[i]),
                                            source="bitview",
                                        )
                                        await self.db.save_onchain_metric(record)
                                        logger.info("Bitview {} (fallback idx {}): {}", db_name, i, record.value)
                                        break
                except Exception as e:
                    logger.error("Bitview error {}: {}", series_name, e)

            await asyncio.sleep(3600)

    async def _futures_loop(self) -> None:
        while self._running:
            try:
                await self._bybit_funding_rate()
                await self._bybit_long_short_ratio()
                await self._okx_open_interest()
            except Exception as e:
                logger.error("Futures loop error: {}", e)
            await asyncio.sleep(300)

    async def _bybit_funding_rate(self) -> None:
        try:
            async with self._session.get(
                f"{BYBIT_BASE}/funding/history",
                params={"category": "linear", "symbol": "BTCUSDT", "limit": 1},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        now = datetime.now(timezone.utc)
                        record = OnchainMetric(
                            time=now, metric_name="funding_rate",
                            value=float(items[0]["fundingRate"]), source="bybit",
                        )
                        await self.db.save_onchain_metric(record)
        except Exception as e:
            logger.error("Bybit funding rate error: {}", e)

    async def _bybit_long_short_ratio(self) -> None:
        try:
            async with self._session.get(
                f"{BYBIT_BASE}/account-ratio",
                params={"category": "linear", "symbol": "BTCUSDT", "period": "1h", "limit": 1},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        buy = float(items[0]["buyRatio"])
                        sell = float(items[0]["sellRatio"])
                        ratio = buy / sell if sell else 1.0
                        now = datetime.now(timezone.utc)
                        record = OnchainMetric(
                            time=now, metric_name="long_short_ratio",
                            value=ratio, source="bybit",
                        )
                        await self.db.save_onchain_metric(record)
        except Exception as e:
            logger.error("Bybit L/S ratio error: {}", e)

    async def _okx_open_interest(self) -> None:
        try:
            async with self._session.get(
                f"{OKX_BASE}/open-interest",
                params={"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", [])
                    if items:
                        now = datetime.now(timezone.utc)
                        record = OnchainMetric(
                            time=now, metric_name="open_interest",
                            value=float(items[0]["oi"]), source="okx",
                        )
                        await self.db.save_onchain_metric(record)
        except Exception as e:
            logger.error("OKX open interest error: {}", e)


async def main() -> None:
    import redis.asyncio as aioredis

    db = Database(settings.database_url)
    await db.connect()

    r = aioredis.from_url(settings.redis_url)
    collector = PriceCollector(db, r, settings)
    await collector.start()


if __name__ == "__main__":
    asyncio.run(main())
