import json
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from loguru import logger


class FearGreedIndex:
    API_URL = "https://api.alternative.me/fng/?limit=1"
    CACHE_KEY = "fear_greed"
    CACHE_TTL = 3600

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def fetch(self) -> Optional[dict]:
        cached = await self._get_cached()
        if cached is not None:
            return cached

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.API_URL, timeout=10) as resp:
                    if resp.status != 200:
                        logger.warning("Fear & Greed API returned {}", resp.status)
                        return await self._stale_fallback()
                    data = await resp.json()
        except Exception as e:
            logger.warning("Fear & Greed API error: {}", e)
            return await self._stale_fallback()

        entries = data.get("data", [])
        if not entries:
            return await self._stale_fallback()

        entry = entries[0]
        try:
            value = int(entry.get("value", 50))
        except (ValueError, TypeError):
            value = 50
        classification = entry.get("value_classification", "Neutral")

        result = {
            "value": value,
            "classification": classification,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            await self.redis.setex(self.CACHE_KEY, self.CACHE_TTL, json.dumps(result))
        except Exception:
            pass

        return result

    async def _get_cached(self) -> Optional[dict]:
        try:
            raw = await self.redis.get(self.CACHE_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    async def _stale_fallback(self) -> Optional[dict]:
        try:
            raw = await self.redis.get(self.CACHE_KEY)
            if raw:
                logger.info("Fear & Greed: using stale cache")
                return json.loads(raw)
        except Exception:
            pass
        return None
