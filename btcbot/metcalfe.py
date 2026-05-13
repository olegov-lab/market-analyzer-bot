import json
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional
from loguru import logger

BLOCKCHAIN_URL = "https://api.blockchain.info/charts/n-unique-addresses"
CACHE_KEY = "metcalfe:corridor"
CACHE_TTL = 21600  # 6 hours


class MetcalfeEngine:
    def __init__(self, db, redis_client):
        self.db = db
        self.redis = redis_client

    async def compute(self, lookback_days: int = 365) -> Optional[dict]:
        cached = await self.redis.get(CACHE_KEY)
        if cached:
            return json.loads(cached)

        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        price_rows = await self.db.get_daily_candles_since("BTCUSD", since)
        addr_rows = await self.db.get_onchain_metric_since("active_addresses", since)

        if not price_rows or not addr_rows:
            logger.warning("Metcalfe: not enough data (prices={}, addrs={})",
                           len(price_rows or []), len(addr_rows or []))
            return None

        price_map = {}
        for r in price_rows:
            d = r["bucket"].date() if hasattr(r["bucket"], "date") else r["bucket"]
            if hasattr(d, "date"):
                d = d.date()
            price_map[d] = float(r["close"])

        addr_map = {}
        for r in addr_rows:
            d = r["time"].date() if hasattr(r["time"], "date") else r["time"]
            if hasattr(d, "date"):
                d = d.date()
            addr_map[d] = float(r["value"])

        common_dates = sorted(set(price_map.keys()) & set(addr_map.keys()))
        ks = []
        for d in common_dates:
            p = price_map[d]
            a = addr_map[d]
            if a > 0:
                ks.append(p / (a * a / 1e9))

        if len(ks) < 30:
            logger.warning("Metcalfe: only {} aligned days, need 30+", len(ks))
            return None

        k_median = float(np.median(ks))
        latest_date = common_dates[-1]
        current_price = price_map[latest_date]
        current_addr = addr_map[latest_date]
        metcalfe_price = k_median * (current_addr * current_addr / 1e9)

        upper = metcalfe_price * 1.30
        lower = metcalfe_price * 0.70
        deviation_pct = round((current_price - metcalfe_price) / metcalfe_price * 100, 1)

        if deviation_pct > 15:
            signal = "overvalued"
        elif deviation_pct < -15:
            signal = "undervalued"
        else:
            signal = "fair"

        history = []
        for d in common_dates[-90:]:
            a = addr_map[d]
            mp = k_median * (a * a / 1e9)
            history.append({
                "time": d.isoformat(),
                "metcalfe_price": round(mp, 2),
                "actual_price": round(price_map[d], 2),
                "upper": round(mp * 1.30, 2),
                "lower": round(mp * 0.70, 2),
                "addresses": int(a),
            })

        result = {
            "time": datetime.now(timezone.utc).isoformat(),
            "active_addresses": int(current_addr),
            "metcalfe_price": round(metcalfe_price, 2),
            "upper_band": round(upper, 2),
            "lower_band": round(lower, 2),
            "actual_price": round(current_price, 2),
            "deviation_pct": deviation_pct,
            "coefficient_k": round(k_median, 8),
            "signal": signal,
            "history": history,
            "dataset_days": len(ks),
        }

        await self.redis.setex(CACHE_KEY, CACHE_TTL, json.dumps(result, default=str))
        return result
