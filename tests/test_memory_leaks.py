"""Tests for memory leak prevention."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from btcbot.alerts import AlertManager, COOLDOWN_MINUTES
from btcbot.collector import VolumeTracker
from bot.state import _ts_tz_cache, _MAX_TZ_CACHE, _tz_for


class TestAlertManagerMemoryLeak:
    def make_alert_manager(self):
        db = AsyncMock()
        redis = AsyncMock()
        bot = AsyncMock()
        am = AlertManager(db, redis, bot)
        am.db = db
        am.redis = redis
        am.bot = bot
        return am

    def test_cooldown_dict_does_not_grow_unbounded(self):
        am = self.make_alert_manager()
        old = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_MINUTES / 60 + 1)
        for i in range(100):
            am._last_sent[f"{i}:rsi"] = old
        assert len(am._last_sent) == 100
        am._set_cooldown(999, "rsi")
        am._cleanup_cooldowns()
        assert len(am._last_sent) <= 1

    def test_cleanup_removes_only_expired(self):
        am = self.make_alert_manager()
        now = datetime.now(timezone.utc)
        am._last_sent["fresh:rsi"] = now
        am._last_sent["old:rsi"] = now - timedelta(hours=COOLDOWN_MINUTES / 60 + 1)
        am._cleanup_cooldowns()
        assert "fresh:rsi" in am._last_sent
        assert "old:rsi" not in am._last_sent

    @pytest.mark.asyncio
    async def test_send_alert_triggers_cleanup_at_threshold(self):
        am = self.make_alert_manager()
        now = datetime.now(timezone.utc)
        expired = now - timedelta(hours=COOLDOWN_MINUTES / 60 + 1)
        for i in range(10001):
            am._last_sent[f"{i}:test"] = expired
        assert len(am._last_sent) == 10001
        am._is_on_cooldown = MagicMock(return_value=False)
        am._set_cooldown = MagicMock()
        am.bot.send_message = AsyncMock()
        am.db.pool = MagicMock()
        am.db.pool.execute = AsyncMock(return_value=None)
        await am._send_alert(99999, "test", 100000, "test")
        assert len(am._last_sent) < 500


class TestTzCacheMemoryLeak:
    @pytest.mark.asyncio
    async def test_cache_clears_at_max(self):
        _ts_tz_cache.clear()
        for i in range(_MAX_TZ_CACHE):
            _ts_tz_cache[i] = "Europe/Moscow"
        assert len(_ts_tz_cache) == _MAX_TZ_CACHE
        with patch("bot.state.db") as mock_db:
            mock_db.get_user_timezone = AsyncMock(return_value="Europe/London")
            await _tz_for(999999)
        assert len(_ts_tz_cache) == 1
        assert _ts_tz_cache.get(999999) == "Europe/London"

    @pytest.mark.asyncio
    async def test_cache_does_not_clear_below_max(self):
        _ts_tz_cache.clear()
        for i in range(_MAX_TZ_CACHE - 1):
            _ts_tz_cache[i] = "Europe/Moscow"
        with patch("bot.state.db") as mock_db:
            mock_db.get_user_timezone = AsyncMock(return_value="Europe/London")
            await _tz_for(999999)
        assert len(_ts_tz_cache) == _MAX_TZ_CACHE

    def test_cache_constant_is_reasonable(self):
        assert _MAX_TZ_CACHE == 1000


class TestVolumeTrackerMemory:
    def test_deque_prunes_old_entries(self):
        redis = AsyncMock()
        vt = VolumeTracker(redis, window=3600)
        now = datetime.now(timezone.utc)
        for i in range(100):
            vt._volumes.append((now - timedelta(seconds=7200 + i), float(i)))
        assert len(vt._volumes) == 100
        vt.add(100.0, now)
        assert len(vt._volumes) <= 2

    def test_deque_bounded_under_heavy_load(self):
        redis = AsyncMock()
        vt = VolumeTracker(redis, window=60)
        now = datetime.now(timezone.utc)
        for i in range(50000):
            t = now - timedelta(hours=2) + timedelta(milliseconds=i)
            vt._volumes.append((t, float(i)))
        assert len(vt._volumes) == 50000
        vt.add(100.0, now)
        assert len(vt._volumes) < 100

    def test_high_frequency_entries_within_window_kept_but_pruned_after(self):
        redis = AsyncMock()
        vt = VolumeTracker(redis, window=3600)
        now = datetime.now(timezone.utc)
        for i in range(200000):
            t = now - timedelta(hours=48) + timedelta(milliseconds=i)
            vt._volumes.append((t, float(i)))
        assert len(vt._volumes) == 200000
        vt.add(100.0, now)
        assert len(vt._volumes) < 5000


class TestGlobalAnalyzerUsage:
    @pytest.mark.asyncio
    async def test_fallback_analysis_uses_global_analyzer(self):
        from backend.api import _fallback_analysis, analyzer
        with patch("backend.api.db") as mock_db, \
             patch("backend.api.analyzer") as mock_analyzer:
            mock_db.get_latest_price = AsyncMock(return_value=100000.0)
            mock_analyzer.compute_consensus = AsyncMock(return_value={"bullish_pct": 50, "signal": "neutral"})
            result = await _fallback_analysis("test question")
            assert result is not None
            assert "BTC" in result or "100" in result
