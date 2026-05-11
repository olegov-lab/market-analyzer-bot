"""Seed 90 days of hourly BTC/USD prices from CoinGecko free API."""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import aiohttp

from btcbot.config import settings
from btcbot.db import Database
from btcbot.models import PriceRecord

COINGECKO_CHART = f"{settings.coingecko_api_url}/coins/bitcoin/market_chart"


async def seed(db: Database, days: int = 90) -> int:
    async with db.pool.acquire() as conn:
        count_row = await conn.fetchrow("SELECT COUNT(*) FROM prices WHERE symbol = 'BTCUSD' AND source = 'coingecko_seed'")
        if count_row and count_row[0] > 100:
            print(f"[seed] Already have {count_row[0]} seeded records, skipping")
            return 0

    print(f"[seed] Fetching {days} days of BTC/USD history from CoinGecko...")
    async with aiohttp.ClientSession() as session:
        url = f"{COINGECKO_CHART}?vs_currency=usd&days={days}"
        async with session.get(url) as resp:
            if resp.status == 429:
                print("[seed] CoinGecko rate limited, retry in 60s...")
                await asyncio.sleep(60)
                async with session.get(url) as resp2:
                    if resp2.status != 200:
                        print(f"[seed] CoinGecko error: {resp2.status}")
                        return 0
                    data = await resp2.json()
            elif resp.status != 200:
                print(f"[seed] CoinGecko error: {resp.status}")
                return 0
            else:
                data = await resp.json()

    prices = data.get("prices", [])
    volumes = data.get("total_volumes", [])
    if not prices:
        print("[seed] No price data returned")
        return 0

    records = []
    vol_map = {v[0]: v[1] for v in volumes} if volumes else {}
    for ts_ms, price in prices:
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        volume = vol_map.get(ts_ms, 0)
        records.append(PriceRecord(
            time=ts, symbol="BTCUSD", price=price, volume=volume, source="coingecko_seed",
        ))

    batch_size = 100
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        await db.save_prices_batch(batch)
        if (i + batch_size) % 500 == 0:
            print(f"[seed] Inserted {min(i + batch_size, len(records))}/{len(records)}")

    print(f"[seed] Done: {len(records)} hourly candles seeded ({days} days)")
    return len(records)


async def main() -> None:
    db = Database(settings.database_url)
    await db.connect()
    try:
        n = await seed(db, days=90)
        print(f"[seed] Seeded {n} records")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
