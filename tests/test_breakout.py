import json
from unittest.mock import AsyncMock

import pytest

from btcbot.breakout import ProactiveAlertEngine, TRIGGERS


class TestProactiveAlertEngine:
    def make_engine(self):
        db = AsyncMock()
        redis = AsyncMock()
        return ProactiveAlertEngine(db, redis)

    def test_triggers_have_cooldown_values(self):
        assert len(TRIGGERS) == 7
        for ttl in TRIGGERS.values():
            assert ttl > 0

    @pytest.mark.asyncio
    async def test_check_all_with_no_data(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        engine.redis.exists = AsyncMock(return_value=False)
        engine.db.get_onchain_metric_since = AsyncMock(return_value=[])

        results = await engine.check_all()
        assert results == []

    @pytest.mark.asyncio
    async def test_is_cooldown_true(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=True)
        assert await engine._is_cooldown("ma_cross") is True

    @pytest.mark.asyncio
    async def test_is_cooldown_false(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        assert await engine._is_cooldown("ma_cross") is False

    @pytest.mark.asyncio
    async def test_set_cooldown(self):
        engine = self.make_engine()
        engine.redis.setex = AsyncMock()
        await engine._set_cooldown("ma_cross", 86400)
        engine.redis.setex.assert_called_once()
        args = engine.redis.setex.call_args[0]
        assert "ma_cross" in args[0]
        assert args[1] == 86400

    @pytest.mark.asyncio
    async def test_queue_alert(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        engine.redis.set = AsyncMock()

        await engine._queue_alert("ma_cross", "Golden cross!")
        engine.redis.set.assert_called_once()
        args = engine.redis.set.call_args[0]
        events = json.loads(args[1])
        assert len(events) == 1
        assert events[0]["trigger"] == "ma_cross"

    @pytest.mark.asyncio
    async def test_read_indicators(self):
        engine = self.make_engine()
        data = {"rsi": 55.0, "ma_50": 98000, "ma_200": 95000}
        engine.redis.get = AsyncMock(return_value=json.dumps(data))
        result = await engine._read_indicators()
        assert result == data

    @pytest.mark.asyncio
    async def test_read_indicators_none(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        result = await engine._read_indicators()
        assert result is None

    @pytest.mark.asyncio
    async def test_read_price(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value="100000.5")
        result = await engine._read_price()
        assert result == 100000.5

    @pytest.mark.asyncio
    async def test_rsi_extreme_no_data(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        engine.redis.exists = AsyncMock(return_value=False)
        result = await engine._check_rsi_extreme()
        assert result is None

    @pytest.mark.asyncio
    async def test_rsi_extreme_normal(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        # is_cooldown → read_indicators → read_price (always, before checking rsi thresholds)
        engine.redis.get = AsyncMock(side_effect=[
            json.dumps({"rsi": 50.0}),  # _read_indicators
            "100000",                     # _read_price
        ])

        result = await engine._check_rsi_extreme()
        assert result is None

    @pytest.mark.asyncio
    async def test_ma_cross_first_run_no_prev_state(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.set = AsyncMock()
        engine.redis.get = AsyncMock(side_effect=[
            json.dumps({"ma_50": 98000, "ma_200": 95000}),
            "100000",
            None,
        ])

        result = await engine._check_ma_cross()
        assert result is None

    @pytest.mark.asyncio
    async def test_bb_touch_upper(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.setex = AsyncMock()
        engine.redis.get = AsyncMock(side_effect=[
            json.dumps({"bb_upper": 105000, "bb_lower": 95000, "bb_middle": 100000}),
            "104600",
        ])

        result = await engine._check_bb_touch()
        assert result is not None
        assert result["trigger"] == "bb_touch"

    @pytest.mark.asyncio
    async def test_bb_touch_lower(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.setex = AsyncMock()
        engine.redis.get = AsyncMock(side_effect=[
            json.dumps({"bb_upper": 105000, "bb_lower": 95000, "bb_middle": 100000}),
            "95400",
        ])

        result = await engine._check_bb_touch()
        assert result is not None
        assert result["trigger"] == "bb_touch"

    @pytest.mark.asyncio
    async def test_bb_touch_no_touch(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.get = AsyncMock(side_effect=[
            json.dumps({"bb_upper": 105000, "bb_lower": 95000, "bb_middle": 100000}),
            "100000",
        ])

        result = await engine._check_bb_touch()
        assert result is None

    @pytest.mark.asyncio
    async def test_fg_extreme_fear(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.setex = AsyncMock()
        engine.redis.get = AsyncMock(return_value=json.dumps({"value": 15, "classification": "Extreme Fear"}))

        result = await engine._check_fg_extreme()
        assert result is not None
        assert "страх" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_fg_extreme_normal(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.get = AsyncMock(return_value=json.dumps({"value": 50, "classification": "Neutral"}))

        result = await engine._check_fg_extreme()
        assert result is None

    @pytest.mark.asyncio
    async def test_vol_spike_triggered(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.setex = AsyncMock()
        engine.redis.get = AsyncMock(side_effect=["1000", "3500", "100000"])

        result = await engine._check_vol_spike()
        assert result is not None
        assert result["trigger"] == "vol_spike"

    @pytest.mark.asyncio
    async def test_vol_spike_below_threshold(self):
        engine = self.make_engine()
        engine.redis.exists = AsyncMock(return_value=False)
        engine.redis.get = AsyncMock(side_effect=["1000", "2000"])

        result = await engine._check_vol_spike()
        assert result is None
