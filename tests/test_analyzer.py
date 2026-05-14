from unittest.mock import AsyncMock, MagicMock

import pytest

from btcbot.analyzer import Analyzer


class TestAnalyzerBBPosition:
    def test_bb_position_normal(self):
        ind = MagicMock()
        ind.bb_lower = 95000
        ind.bb_upper = 105000
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 100000)
        assert result == 50.0

    def test_bb_position_at_lower(self):
        ind = MagicMock()
        ind.bb_lower = 95000
        ind.bb_upper = 105000
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 95000)
        assert result == 0.0

    def test_bb_position_at_upper(self):
        ind = MagicMock()
        ind.bb_lower = 95000
        ind.bb_upper = 105000
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 105000)
        assert result == 100.0

    def test_bb_position_below_range_clamped(self):
        ind = MagicMock()
        ind.bb_lower = 95000
        ind.bb_upper = 105000
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 90000)
        assert result == 0.0

    def test_bb_position_above_range_clamped(self):
        ind = MagicMock()
        ind.bb_lower = 95000
        ind.bb_upper = 105000
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 110000)
        assert result == 100.0

    def test_bb_position_zero_denom(self):
        ind = MagicMock()
        ind.bb_lower = 100000
        ind.bb_upper = 100000
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 100000)
        assert result is None

    def test_bb_position_missing_bands(self):
        ind = MagicMock()
        ind.bb_lower = None
        ind.bb_upper = None
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(ind, 100000)
        assert result is None

    def test_bb_position_missing_price(self):
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.redis = AsyncMock()
        result = analyzer._bb_position(None, None)
        assert result is None


class TestAnalyzerConsensus:
    def _make_indicators(self, **overrides):
        ind = MagicMock()
        ind.ma_50 = overrides.get("ma_50", None)
        ind.ma_200 = overrides.get("ma_200", None)
        ind.ma_100 = None
        ind.rsi = overrides.get("rsi", 50.0)
        ind.macd = 0.0
        ind.macd_signal = -0.1
        ind.bb_lower = overrides.get("bb_lower", None)
        ind.bb_upper = overrides.get("bb_upper", None)
        ind.bb_middle = None
        ind.funding_rate = 0.005
        ind.model_dump = MagicMock(return_value={})
        return ind

    @pytest.mark.asyncio
    async def test_consensus_returns_from_cache(self):
        import json
        redis = AsyncMock()
        cached = json.dumps({"bullish_pct": 65, "bearish_pct": 35, "signal": "bullish", "available": 5, "low_confidence": False})
        redis.get = AsyncMock(return_value=cached)
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.db = AsyncMock()
        analyzer.redis = redis
        result = await analyzer.compute_consensus()
        assert result["bullish_pct"] == 65

    @pytest.mark.asyncio
    async def test_consensus_no_indicators_returns_default(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        analyzer = Analyzer.__new__(Analyzer)
        analyzer.db = AsyncMock()
        analyzer.redis = redis
        analyzer.compute_indicators = AsyncMock(return_value=None)

        result = await analyzer.compute_consensus()
        assert result["bullish_pct"] == 50
        assert result["signal"] == "neutral"
        assert result["low_confidence"] is True
