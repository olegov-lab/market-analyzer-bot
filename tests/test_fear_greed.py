import json
from unittest.mock import AsyncMock

import pytest

from btcbot.fear_greed import FearGreedIndex


class TestFearGreedIndex:
    def make_fng(self, redis_mock=None):
        redis = redis_mock or AsyncMock()
        return FearGreedIndex(redis)

    @pytest.mark.asyncio
    async def test_returns_cached_value(self):
        redis = AsyncMock()
        cached = json.dumps({"value": 55, "classification": "Greed", "timestamp": "2025-01-01T00:00:00"})
        redis.get = AsyncMock(return_value=cached)
        fng = self.make_fng(redis)
        result = await fng.fetch()
        assert result["value"] == 55
        assert result["classification"] == "Greed"
        redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_cached_returns_none_when_empty(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fng = self.make_fng(redis)
        result = await fng._get_cached()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_parses_json(self):
        redis = AsyncMock()
        data = {"value": 60, "classification": "Greed"}
        redis.get = AsyncMock(return_value=json.dumps(data))
        fng = self.make_fng(redis)
        result = await fng._get_cached()
        assert result == data

    @pytest.mark.asyncio
    async def test_stale_fallback_returns_none_when_no_cache(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fng = self.make_fng(redis)
        result = await fng._stale_fallback()
        assert result is None

    @pytest.mark.asyncio
    async def test_stale_fallback_returns_cached(self):
        redis = AsyncMock()
        data = {"value": 30, "classification": "Fear"}
        redis.get = AsyncMock(return_value=json.dumps(data))
        fng = self.make_fng(redis)
        result = await fng._stale_fallback()
        assert result == data

    @pytest.mark.asyncio
    async def test_redis_exception_is_handled(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        fng = self.make_fng(redis)
        result = await fng._get_cached()
        assert result is None
        result = await fng._stale_fallback()
        assert result is None
