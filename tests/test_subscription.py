import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from btcbot.subscription import (
    Tier,
    TIER_PRICES,
    get_user_tier,
    has_feature,
    activate_trial,
    activate_pro,
    activate_pro_plus,
    FREE_FEATURES,
    PRO_FEATURES,
    PRO_PLUS_FEATURES,
)


def _now():
    return datetime.now(timezone.utc)


def _future(hours=72):
    return _now() + timedelta(hours=hours)


def _past(hours=72):
    return _now() - timedelta(hours=hours)


class TestTierEnum:
    def test_tier_values(self):
        assert Tier.FREE == "free"
        assert Tier.PRO == "pro"
        assert Tier.PRO_PLUS == "pro_plus"

    def test_tier_prices(self):
        assert TIER_PRICES["pro"]["stars"] == 80
        assert TIER_PRICES["pro_plus"]["stars"] == 200


class TestFeatureSets:
    def test_free_features_exist(self):
        assert "dashboard" in FREE_FEATURES
        assert "game" in FREE_FEATURES

    def test_pro_features_superset(self):
        assert FREE_FEATURES.issubset(PRO_FEATURES)
        assert "ask_unlimited" in PRO_FEATURES
        assert "ask_unlimited" not in FREE_FEATURES

    def test_pro_plus_features_superset(self):
        assert PRO_FEATURES.issubset(PRO_PLUS_FEATURES)
        assert "voice_input" in PRO_PLUS_FEATURES


class TestGetUserTier:
    @pytest.mark.asyncio
    async def test_no_row_returns_free(self, mock_db, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        tier = await get_user_tier(mock_db, 12345)
        assert tier == Tier.FREE

    @pytest.mark.asyncio
    async def test_active_pro_plus_returns_pro_plus(self, mock_db, mock_conn):
        row = {"tier": "pro_plus", "trial_until": None, "pro_until": None, "pro_plus_until": _future()}
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.fetchval = AsyncMock(return_value=_now())
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        tier = await get_user_tier(mock_db, 12345)
        assert tier == Tier.PRO_PLUS

    @pytest.mark.asyncio
    async def test_expired_pro_returns_free(self, mock_db, mock_conn):
        row = {"tier": "pro", "trial_until": None, "pro_until": _past(), "pro_plus_until": None}
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.fetchval = AsyncMock(return_value=_now())
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        tier = await get_user_tier(mock_db, 12345)
        assert tier == Tier.FREE

    @pytest.mark.asyncio
    async def test_active_trial_returns_pro(self, mock_db, mock_conn):
        row = {"tier": "free", "trial_until": _future(), "pro_until": None, "pro_plus_until": None}
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.fetchval = AsyncMock(return_value=_now())
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        tier = await get_user_tier(mock_db, 12345)
        assert tier == Tier.PRO


class TestHasFeature:
    @pytest.mark.asyncio
    async def test_free_user_has_free_feature(self, mock_db, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await has_feature(mock_db, 12345, "dashboard")
        assert result is True

    @pytest.mark.asyncio
    async def test_free_user_lacks_pro_feature(self, mock_db, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await has_feature(mock_db, 12345, "ask_unlimited")
        assert result is False

    @pytest.mark.asyncio
    async def test_pro_user_has_pro_feature(self, mock_db, mock_conn):
        row = {"tier": "pro", "trial_until": None, "pro_until": _future(), "pro_plus_until": None}
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.fetchval = AsyncMock(return_value=_now())
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await has_feature(mock_db, 12345, "ask_unlimited")
        assert result is True


class TestActivatePro:
    @pytest.mark.asyncio
    async def test_activate_pro_calls_execute(self, mock_db, mock_conn):
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        await activate_pro(mock_db, 12345, days=30)
        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert 12345 in args
        assert "30" in args


class TestActivateTrial:
    @pytest.mark.asyncio
    async def test_activate_trial_calls_execute(self, mock_db, mock_conn):
        mock_db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        await activate_trial(mock_db, 12345)
        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert 12345 in args
