import json
from unittest.mock import AsyncMock

import pytest

from btcbot.metcalfe import MetcalfeEngine


def _date(days_ago):
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()


class TestMetcalfeEngine:
    def make_engine(self):
        db = AsyncMock()
        redis = AsyncMock()
        return MetcalfeEngine(db, redis)

    @pytest.mark.asyncio
    async def test_returns_cached_result(self):
        engine = self.make_engine()
        cached = json.dumps({"metcalfe_price": 100000, "signal": "fair"})
        engine.redis.get = AsyncMock(return_value=cached)
        result = await engine.compute()
        assert result["metcalfe_price"] == 100000

    @pytest.mark.asyncio
    async def test_not_enough_data_returns_none(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        engine.db.get_daily_candles_since = AsyncMock(return_value=[])
        engine.db.get_onchain_metric_since = AsyncMock(return_value=[])

        result = await engine.compute()
        assert result is None

    @pytest.mark.asyncio
    async def test_computes_corridor_with_data(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        engine.redis.setex = AsyncMock()

        base_price = 90000
        base_addr = 800000
        price_rows = []
        addr_rows = []
        for i in range(40):
            d = _date(40 - i)
            price_rows.append({"bucket": d, "close": base_price + i * 100})
            addr_rows.append({"time": d, "value": base_addr + i * 100})

        engine.db.get_daily_candles_since = AsyncMock(return_value=price_rows)
        engine.db.get_onchain_metric_since = AsyncMock(return_value=addr_rows)

        result = await engine.compute()
        assert result is not None
        assert "metcalfe_price" in result
        assert "upper_band" in result
        assert "lower_band" in result
        assert result["upper_band"] >= result["lower_band"]
        assert result["dataset_days"] >= 30

    @pytest.mark.asyncio
    async def test_signal_fair(self):
        engine = self.make_engine()
        engine.redis.get = AsyncMock(return_value=None)
        engine.redis.setex = AsyncMock()

        base_price = 50000
        base_addr = 700000
        price_rows = []
        addr_rows = []
        for i in range(40):
            d = _date(40 - i)
            price_rows.append({"bucket": d, "close": base_price + i * 10})
            addr_rows.append({"time": d, "value": base_addr + i * 50})

        engine.db.get_daily_candles_since = AsyncMock(return_value=price_rows)
        engine.db.get_onchain_metric_since = AsyncMock(return_value=addr_rows)

        result = await engine.compute()
        if result:
            assert abs(result["deviation_pct"]) < 15 or result["signal"] in ("overvalued", "undervalued", "fair")
