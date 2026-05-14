import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from btcbot.summarizer import summarize_indicators


class TestSummarizeIndicators:
    @pytest.mark.asyncio
    async def test_returns_cached_summary(self):
        redis = AsyncMock()
        cached = json.dumps({"trend": "Бычий тренд", "momentum": "", "volatility": "", "onchain": "", "sentiment": ""})
        redis.get = AsyncMock(return_value=cached)
        db = AsyncMock()

        result = await summarize_indicators(db, redis, None, None, None, None)
        assert result["trend"] == "Бычий тренд"

    @pytest.mark.asyncio
    async def test_no_indicators_returns_empty(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        db = AsyncMock()

        result = await summarize_indicators(db, redis, None, None, None, None)
        assert result == {"trend": "", "momentum": "", "volatility": "", "onchain": "", "sentiment": ""}

    @pytest.mark.asyncio
    async def test_builds_groups_with_valid_indicators(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        db = AsyncMock()

        ind = MagicMock()
        ind.ma_50 = 98000
        ind.ma_200 = 95000
        ind.rsi = 55.0
        ind.macd = 100.0
        ind.macd_signal = 50.0
        ind.bb_lower = 94000
        ind.bb_middle = 100000
        ind.bb_upper = 106000
        ind.atr_pct = 2.5
        ind.funding_rate = 0.005

        fng = {"value": 60, "classification": "Greed"}
        onchain = {"mvrv_z": 2.1, "sopr": 1.05, "nupl": 0.55, "cycle_phase": "Belief"}

        with patch("backend.agents.ask_agent") as mock_ask:
            mock_ask.return_value = "Краткая сводка группы"
            result = await summarize_indicators(db, redis, 100000, ind, fng, onchain)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"trend", "momentum", "volatility", "onchain", "sentiment"}

    @pytest.mark.asyncio
    async def test_agent_error_returns_empty_for_all_groups(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        db = AsyncMock()

        ind = MagicMock()
        ind.ma_50 = 98000
        ind.ma_200 = 95000
        ind.rsi = 55.0
        ind.macd = 100.0
        ind.macd_signal = 50.0
        ind.bb_lower = 94000
        ind.bb_middle = 100000
        ind.bb_upper = 106000
        ind.atr_pct = 2.5

        with patch("backend.agents.ask_agent") as mock_ask:
            mock_ask.return_value = "[Agent error: timeout]"
            result = await summarize_indicators(db, redis, 100000, ind, None, None)

        for v in result.values():
            assert v == ""

    @pytest.mark.asyncio
    async def test_graceful_fallback_on_exception(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        db = AsyncMock()

        ind = MagicMock()
        ind.ma_50 = None
        ind.ma_200 = None
        ind.rsi = None
        ind.macd = None
        ind.macd_signal = None
        ind.bb_lower = None
        ind.atr_pct = None

        result = await summarize_indicators(db, redis, None, ind, None, None)
        assert result == {"trend": "", "momentum": "", "volatility": "", "onchain": "", "sentiment": ""}

    @pytest.mark.asyncio
    async def test_ask_agent_exception_is_handled(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        db = AsyncMock()

        ind = MagicMock()
        ind.ma_50 = 98000
        ind.ma_200 = 95000
        ind.rsi = 55.0
        ind.macd = 100.0
        ind.macd_signal = 50.0
        ind.bb_lower = 94000
        ind.bb_middle = 100000
        ind.bb_upper = 106000
        ind.atr_pct = 2.5

        with patch("backend.agents.ask_agent") as mock_ask:
            mock_ask.side_effect = RuntimeError("API down")
            result = await summarize_indicators(db, redis, 100000, ind, None, None)

        assert result["trend"] == ""
