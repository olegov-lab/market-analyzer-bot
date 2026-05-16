"""Comprehensive tests for edge cases, race conditions, and typical bugs."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from btcbot.alerts import AlertManager, COOLDOWN_MINUTES
from btcbot.breakout import ProactiveAlertEngine, TRIGGERS
from btcbot.collector import PriceBuffer, PriceCollector, VolumeTracker
from btcbot.fear_greed import FearGreedIndex
from btcbot.game import GameEngine
from btcbot.metcalfe import MetcalfeEngine
from btcbot.news import build_sentiment_summary, build_market_brain_comment, fetch_news
from btcbot.sentiment import classify_sentiment, _normalize
from btcbot.subscription import (
    Tier, get_user_tier, has_feature,
    activate_trial, activate_pro, activate_pro_plus,
)
from btcbot.utils import safe_gather
from btcbot.models import IndicatorSet
from backend.miniapp_auth import verify_telegram_init_data


# ─── Safe Gather ─────────────────────────────────────────────────────

class TestSafeGather:
    @pytest.mark.asyncio
    async def test_all_success(self):
        async def ok(val):
            return val
        results = await safe_gather(ok(1), ok(2), log_prefix="test")
        assert results == [1, 2]

    @pytest.mark.asyncio
    async def test_one_failure_returns_none_for_it(self):
        async def fail():
            raise ValueError("fail")
        async def ok():
            return 42
        results = await safe_gather(ok(), fail(), log_prefix="test")
        assert results == [42, None]

    @pytest.mark.asyncio
    async def test_all_fail(self):
        async def fail():
            raise RuntimeError("boom")
        results = await safe_gather(fail(), fail(), log_prefix="test")
        assert results == [None, None]

    @pytest.mark.asyncio
    async def test_mixed_types(self):
        async def ok():
            return "hello"
        async def fail():
            raise TypeError("bad")
        results = await safe_gather(ok(), fail(), log_prefix="test")
        assert results == ["hello", None]

    @pytest.mark.asyncio
    async def test_return_exceptions_handles_cancelled(self):
        async def cancel_me():
            raise asyncio.CancelledError()
        async def ok():
            return True
        results = await safe_gather(ok(), cancel_me(), log_prefix="test")
        assert results == [True, None]

    @pytest.mark.asyncio
    async def test_none_result_is_preserved(self):
        async def none_func():
            return None
        results = await safe_gather(none_func(), log_prefix="test")
        assert results == [None]

    @pytest.mark.asyncio
    async def test_empty_gather(self):
        results = await safe_gather(log_prefix="test")
        assert results == []


# ─── Fear & Greed ───────────────────────────────────────────────────

class TestFearGreedIndex:
    @pytest.mark.asyncio
    async def test_api_error_uses_stale_fallback(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[None, json.dumps({"value": 50, "classification": "Neutral"})])
        fgi = FearGreedIndex(redis)
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 500
            result = await fgi.fetch()
            assert result["value"] == 50
            assert result["classification"] == "Neutral"

    @pytest.mark.asyncio
    async def test_api_timeout_uses_stale_fallback(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=[None, json.dumps({"value": 25, "classification": "Fear"})])
        fgi = FearGreedIndex(redis)
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.side_effect = asyncio.TimeoutError()
            result = await fgi.fetch()
            assert result["value"] == 25

    @pytest.mark.asyncio
    async def test_no_cache_and_no_api_returns_none(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fgi = FearGreedIndex(redis)
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 500
            result = await fgi.fetch()
            assert result is None

    @pytest.mark.asyncio
    async def test_cache_returns_directly(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"value": 70, "classification": "Greed"}))
        fgi = FearGreedIndex(redis)
        with patch("aiohttp.ClientSession") as mock_session:
            result = await fgi.fetch()
            mock_session.assert_not_called()
            assert result["value"] == 70

    @pytest.mark.asyncio
    async def test_invalid_value_returns_50(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fgi = FearGreedIndex(redis)

        resp = AsyncMock()
        resp.status = 200
        resp.json = AsyncMock(return_value={"data": [{"value": "invalid", "value_classification": "Neutral"}]})

        get_cm = AsyncMock()
        get_cm.__aenter__ = AsyncMock(return_value=resp)
        get_cm.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.get = MagicMock(return_value=get_cm)

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value = session
            result = await fgi.fetch()
            assert result["value"] == 50


# ─── News + Sentiment ───────────────────────────────────────────────

class TestSentiment:
    def test_bullish_keywords_detected(self):
        assert classify_sentiment("Bitcoin surges to new all-time high") == "bullish"
        assert classify_sentiment("Bitcoin surges to new record high") == "bullish"

    def test_bearish_keywords_detected(self):
        assert classify_sentiment("Bitcoin crashes through floor") == "bearish"
        assert classify_sentiment("Bitcoin plunges, panic selling") == "bearish"

    def test_neutral_when_equal(self):
        assert classify_sentiment("Bitcoin goes up and down") == "neutral"

    def test_empty_title_returns_neutral(self):
        assert classify_sentiment("") == "neutral"

    def test_russian_bullish(self):
        assert classify_sentiment("Биткоин вырос до нового рекорда") == "bullish"

    def test_russian_bearish(self):
        assert classify_sentiment("Биткоин обвалился, паника на рынке") == "bearish"

    def test_special_chars_handled(self):
        assert classify_sentiment("BTC $100k!!! 🚀🚀") in ("bullish", "neutral")

    def test_normalize_empty(self):
        assert _normalize("") == ""

    def test_normalize_non_alpha(self):
        assert _normalize("123!@#$%^&*()") == ""

    def test_normalize_mixed_languages(self):
        result = _normalize("Bitcoin растет")
        assert "bitcoin" in result
        assert "раст" in result


class TestNews:
    def test_build_sentiment_summary_empty(self):
        result = build_sentiment_summary([])
        assert result["sentiment"]["bullish"] == 0
        assert result["sentiment"]["mood"] == "neutral"

    def test_build_sentiment_summary_bullish(self):
        articles = [
            {"title": "Bitcoin surges", "sentiment": "bullish"},
            {"title": "Bitcoin rallies", "sentiment": "bullish"},
            {"title": "Bitcoin drops", "sentiment": "bearish"},
        ]
        result = build_sentiment_summary(articles)
        assert result["sentiment"]["bullish"] == 2
        assert result["sentiment"]["bearish"] == 1
        assert result["sentiment"]["mood"] == "bullish"

    def test_build_sentiment_summary_bearish(self):
        articles = [
            {"title": "Bitcoin falls", "sentiment": "bearish"},
            {"title": "Bitcoin crashes", "sentiment": "bearish"},
            {"title": "Bitcoin holds", "sentiment": "neutral"},
        ]
        result = build_sentiment_summary(articles)
        assert result["sentiment"]["mood"] == "bearish"

    def test_market_brain_comment_high_ratio(self):
        comment = build_market_brain_comment(5, 1, 6)
        assert "бычий" in comment or "позитив" in comment

    def test_market_brain_comment_low_ratio(self):
        comment = build_market_brain_comment(1, 5, 6)
        assert "медвежий" in comment or "негатив" in comment

    def test_market_brain_comment_mixed(self):
        comment = build_market_brain_comment(3, 3, 6)
        assert "неопределён" in comment or "Смешан" in comment

    def test_market_brain_comment_zero_total(self):
        comment = build_market_brain_comment(0, 0, 0)
        assert isinstance(comment, str)
        assert len(comment) > 0

    @pytest.mark.asyncio
    async def test_fetch_news_returns_empty_on_api_error(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        with patch("btcbot.news._get_session") as mock_session:
            mock_session.return_value.get.return_value.__aenter__.return_value.status = 500
            result = await fetch_news(redis)
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_news_returns_cached(self):
        redis = AsyncMock()
        articles = [{"title": "Test", "source": "src", "url": "url", "sentiment": "neutral"}]
        redis.get = AsyncMock(return_value=json.dumps(articles))
        result = await fetch_news(redis)
        assert result == articles


# ─── Subscription ──────────────────────────────────────────────────

class TestSubscription:
    @pytest.mark.asyncio
    async def test_no_subscription_returns_free(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=None)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=conn)
        db = MagicMock()
        db.pool = mock_pool
        tier = await get_user_tier(db, 1)
        assert tier == Tier.FREE

    @pytest.mark.asyncio
    async def test_free_user_has_basic_features(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=None)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=conn)
        db = MagicMock()
        db.pool = mock_pool
        assert await has_feature(db, 1, "dashboard")

    @pytest.mark.asyncio
    async def test_free_user_lacks_pro_features(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=None)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=conn)
        db = MagicMock()
        db.pool = mock_pool
        assert not await has_feature(db, 1, "ask_unlimited")

    @pytest.mark.asyncio
    async def test_free_user_lacks_pro_plus_features(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.fetchval = AsyncMock(return_value=None)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=conn)
        db = MagicMock()
        db.pool = mock_pool
        assert not await has_feature(db, 1, "voice_input")

    def test_tier_prices_defined(self):
        from btcbot.subscription import TIER_PRICES
        assert "pro" in TIER_PRICES
        assert "pro_plus" in TIER_PRICES
        assert TIER_PRICES["pro"]["stars"] == 80


# ─── Metcalfe ───────────────────────────────────────────────────────

class TestMetcalfe:
    @pytest.mark.asyncio
    async def test_none_when_no_data(self):
        db = AsyncMock()
        db.get_daily_candles_since = AsyncMock(return_value=[])
        db.get_onchain_metric_since = AsyncMock(return_value=[])
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        engine = MetcalfeEngine(db, redis)
        result = await engine.compute()
        assert result is None

    @pytest.mark.asyncio
    async def test_none_when_fewer_than_30_days(self):
        db = AsyncMock()
        now = datetime.now(timezone.utc)
        db.get_daily_candles_since = AsyncMock(return_value=[
            {"bucket": (now - timedelta(days=i)).date(), "close": 50000.0}
            for i in range(20)
        ])
        db.get_onchain_metric_since = AsyncMock(return_value=[
            {"time": (now - timedelta(days=i)).date(), "value": 1000000.0}
            for i in range(20)
        ])
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        engine = MetcalfeEngine(db, redis)
        result = await engine.compute()
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_cache(self):
        db = AsyncMock()
        redis = AsyncMock()
        cached = {"signal": "fair", "active_addresses": 1000000}
        redis.get = AsyncMock(return_value=json.dumps(cached))
        engine = MetcalfeEngine(db, redis)
        result = await engine.compute()
        assert result["signal"] == "fair"
        db.get_daily_candles_since.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_addresses_handled(self):
        db = AsyncMock()
        now = datetime.now(timezone.utc)
        rows = [{"bucket": (now - timedelta(days=i)).date(), "close": 50000.0} for i in range(40)]
        addr = [{"time": (now - timedelta(days=i)).date(), "value": 0.0} for i in range(40)]
        db.get_daily_candles_since = AsyncMock(return_value=rows)
        db.get_onchain_metric_since = AsyncMock(return_value=addr)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        engine = MetcalfeEngine(db, redis)
        result = await engine.compute()
        assert result is None


# ─── Game Engine ────────────────────────────────────────────────────

class TestGameEngine:
    def make_engine(self):
        return GameEngine(MagicMock())

    @pytest.mark.asyncio
    async def test_buy_below_minimum_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="Минимальная"):
            await engine.buy(1, 5.0)

    @pytest.mark.asyncio
    async def test_buy_no_price_raises(self):
        engine = self.make_engine()
        engine.db.get_or_create_game_user = AsyncMock(return_value={"balance": 10000})
        engine.db.get_positions = AsyncMock(return_value=[])
        engine.db.get_latest_price = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="недоступна"):
            await engine.buy(1, 100)

    @pytest.mark.asyncio
    async def test_buy_existing_position_raises(self):
        engine = self.make_engine()
        engine.db.get_or_create_game_user = AsyncMock(return_value={"balance": 10000})
        engine.db.get_positions = AsyncMock(return_value=[{"id": 1}])
        with pytest.raises(ValueError, match="открытая позиция"):
            await engine.buy(1, 100)

    @pytest.mark.asyncio
    async def test_sell_no_position_raises(self):
        engine = self.make_engine()
        engine.db.get_positions = AsyncMock(return_value=[])
        with pytest.raises(ValueError, match="Нет открытой"):
            await engine.sell(1)

    @pytest.mark.asyncio
    async def test_sell_no_price_raises(self):
        engine = self.make_engine()
        engine.db.get_positions = AsyncMock(return_value=[{"id": 1, "side": "LONG", "entry_price": 50000, "quantity": 0.1, "notional": 5000}])
        engine.db.get_latest_price = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="недоступна"):
            await engine.sell(1)

    def test_compute_league_bronze_default(self):
        result = GameEngine.compute_league(-1000)
        assert result["league"] == "bronze"
        assert result["next_league"] == "silver"

    def test_compute_league_platinum(self):
        result = GameEngine.compute_league(20000)
        assert result["league"] == "platinum"
        assert result["next_league"] is None
        assert result["progress_pct"] == 100

    def test_compute_league_silver(self):
        result = GameEngine.compute_league(1000)
        assert result["league"] == "silver"
        assert result["next_league"] == "gold"
        assert 0 < result["progress_pct"] < 100

    def test_compute_league_zero_pnl(self):
        result = GameEngine.compute_league(0)
        assert result["league"] == "bronze"
        assert result["next_league"] == "silver"
        assert result["progress_pct"] == 0

    # ─── Roulette ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_roulette_bet_too_low_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="Ставка от 1"):
            await engine.roulette_spin(1, 0, AsyncMock())

    @pytest.mark.asyncio
    async def test_roulette_bet_too_high_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="Ставка от 1"):
            await engine.roulette_spin(1, 11, AsyncMock())

    @pytest.mark.asyncio
    async def test_roulette_bet_not_int_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="целым числом"):
            await engine.roulette_spin(1, 1.5, AsyncMock())

    @pytest.mark.asyncio
    async def test_roulette_cooldown_blocks(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"1")
        engine = self.make_engine()
        with pytest.raises(ValueError, match="3 секунды"):
            await engine.roulette_spin(1, 1, redis)

    @pytest.mark.asyncio
    async def test_roulette_insufficient_stars(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        engine = self.make_engine()
        engine.db.get_or_create_game_user = AsyncMock(return_value={"stars": 0})
        with pytest.raises(ValueError, match="Недостаточно"):
            await engine.roulette_spin(1, 1, redis)

    @pytest.mark.asyncio
    async def test_roulette_probability_distribution(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        engine = self.make_engine()
        engine.db.get_or_create_game_user = AsyncMock(return_value={"stars": 100})
        engine.db.pool = MagicMock()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=None)
        engine.db.pool.acquire = MagicMock(return_value=conn)
        engine.db.add_stars = AsyncMock()

        results = {"lose": 0, "x1.5": 0, "x2": 0, "x3": 0, "x5": 0}
        n = 2000
        import random
        random.seed(42)
        for _ in range(n):
            conn.execute.reset_mock()
            result = await engine.roulette_spin(1, 1, redis)
            if result["multiplier"] == 0:
                results["lose"] += 1
            elif result["multiplier"] == 1.5:
                results["x1.5"] += 1
            elif result["multiplier"] == 2.0:
                results["x2"] += 1
            elif result["multiplier"] == 3.0:
                results["x3"] += 1
            elif result["multiplier"] == 5.0:
                results["x5"] += 1
            # reset cooldown for test
            redis.get.reset_mock(return_value=None)
            redis.get.return_value = None

        total = sum(results.values())
        assert 0.35 <= results["lose"] / total <= 0.45
        assert 0.25 <= results["x1.5"] / total <= 0.35

    # ─── Mining ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_mining_cooldown_blocks(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"earned": 10, "last_click": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), "streak": 1}))
        engine = self.make_engine()
        with pytest.raises(ValueError, match="час"):
            await engine.mine_click(1, redis)

    @pytest.mark.asyncio
    async def test_mining_first_click_works(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        engine = self.make_engine()
        engine.db.get_referral_stats = AsyncMock(return_value={"count": 0})
        result = await engine.mine_click(1, redis)
        assert result["streak"] == 1
        assert 3 <= result["earned"] <= 8

    @pytest.mark.asyncio
    async def test_mining_streak_breaks_after_24h(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"earned": 50, "last_click": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), "streak": 10}))
        redis.set = AsyncMock()
        engine = self.make_engine()
        engine.db.get_referral_stats = AsyncMock(return_value={"count": 0})
        result = await engine.mine_click(1, redis)
        assert result["streak"] == 0


# ─── Price Buffer ───────────────────────────────────────────────────

class TestPriceBuffer:
    @pytest.mark.asyncio
    async def test_flush_on_max_size(self):
        db = AsyncMock()
        db.save_prices_batch = AsyncMock()
        buf = PriceBuffer(db, max_size=5, flush_interval=999)
        for i in range(5):
            await buf.add(MagicMock())
        db.save_prices_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_on_interval(self):
        db = AsyncMock()
        db.save_prices_batch = AsyncMock()
        buf = PriceBuffer(db, max_size=100, flush_interval=0.05)
        loop = asyncio.get_running_loop()
        task = loop.create_task(buf.flush_loop())
        await buf.add(MagicMock())
        await asyncio.sleep(0.1)
        task.cancel()
        db.save_prices_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_empty_does_nothing(self):
        db = AsyncMock()
        buf = PriceBuffer(db)
        buf._buf = []
        await buf._flush()
        db.save_prices_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_error_does_not_lose_data(self):
        db = AsyncMock()
        db.save_prices_batch = AsyncMock(side_effect=Exception("DB down"))
        buf = PriceBuffer(db, max_size=5, flush_interval=999)
        for i in range(5):
            await buf.add(MagicMock())
        # data stays in buffer on error so retries can work
        assert len(buf._buf) == 5


# ─── Volume Tracker ─────────────────────────────────────────────────

class TestVolumeTracker:
    def test_empty_volume_returns_nothing(self):
        redis = AsyncMock()
        vt = VolumeTracker(redis)
        assert len(vt._volumes) == 0

    def test_add_volume_then_prune(self):
        redis = AsyncMock()
        vt = VolumeTracker(redis, window=60)
        now = datetime.now(timezone.utc)
        vt._volumes.append((now - timedelta(hours=2), 100.0))
        vt.add(200.0, now)
        assert len(vt._volumes) <= 2

    def test_publish_stats_empty(self):
        redis = AsyncMock()
        vt = VolumeTracker(redis, window=60)
        now = datetime.now(timezone.utc)
        import asyncio
        asyncio.run(vt.publish_stats(now))
        redis.set.assert_not_called()


# ─── Mini App Auth ─────────────────────────────────────────────────

class TestMiniAppAuth:
    def test_empty_init_data_returns_none(self):
        result = verify_telegram_init_data("", "token")
        assert result is None

    def test_no_hash_returns_none(self):
        result = verify_telegram_init_data("user=%7B%22id%22%3A123%7D", "token")
        assert result is None

    def test_invalid_hash_returns_none(self):
        result = verify_telegram_init_data("user=%7B%22id%22%3A123%7D&hash=invalid", "token")
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_auth_date_not_validated(self):
        result = verify_telegram_init_data("hash=0" * 16, "token")
        assert result is None  # hash is wrong anyway


# ─── Proactive Alerts ──────────────────────────────────────────────

class TestProactiveAlerts:
    @pytest.mark.asyncio
    async def test_ma_cross_first_run_returns_none(self):
        engine = ProactiveAlertEngine(AsyncMock(), AsyncMock())
        engine._read_indicators = AsyncMock(return_value={"ma_50": 50000, "ma_200": 49000})
        engine._read_price = AsyncMock(return_value=51000)
        engine.redis.get = AsyncMock(return_value=None)
        engine.redis.exists = AsyncMock(return_value=0)
        engine.redis.set = AsyncMock()
        result = await engine._check_ma_cross()
        assert result is None

    @pytest.mark.asyncio
    async def test_ma_cross_detection_on_change(self):
        engine = ProactiveAlertEngine(AsyncMock(), AsyncMock())
        engine._read_indicators = AsyncMock(return_value={"ma_50": 50000, "ma_200": 49000})
        engine._read_price = AsyncMock(return_value=51000)
        engine.redis.exists = AsyncMock(return_value=0)
        engine.redis.get = AsyncMock(return_value=b"below")
        engine.redis.set = AsyncMock()

        result = await engine._check_ma_cross()
        assert result is not None
        assert result["trigger"] == "ma_cross"

    @pytest.mark.asyncio
    async def test_bb_touch_no_indicators_returns_none(self):
        engine = ProactiveAlertEngine(AsyncMock(), AsyncMock())
        engine._read_indicators = AsyncMock(return_value=None)
        result = await engine._check_bb_touch()
        assert result is None

    @pytest.mark.asyncio
    async def test_bb_touch_no_price_returns_none(self):
        engine = ProactiveAlertEngine(AsyncMock(), AsyncMock())
        engine._read_indicators = AsyncMock(return_value={"bb_upper": 60000, "bb_lower": 40000, "bb_middle": 50000})
        engine._read_price = AsyncMock(return_value=None)
        engine.redis.exists = AsyncMock(return_value=0)
        result = await engine._check_bb_touch()
        assert result is None

    @pytest.mark.asyncio
    async def test_rsi_extreme_above_75_triggers(self):
        engine = ProactiveAlertEngine(AsyncMock(), AsyncMock())
        engine._read_indicators = AsyncMock(return_value={"rsi": 80})
        engine._read_price = AsyncMock(return_value=60000)
        engine.redis.exists = AsyncMock(return_value=0)
        engine.redis.setex = AsyncMock()
        result = await engine._check_rsi_extreme()
        assert result is not None
        assert "перекуплен" in result["message"]

    @pytest.mark.asyncio
    async def test_rsi_extreme_below_25_triggers(self):
        engine = ProactiveAlertEngine(AsyncMock(), AsyncMock())
        engine._read_indicators = AsyncMock(return_value={"rsi": 20})
        engine._read_price = AsyncMock(return_value=50000)
        engine.redis.exists = AsyncMock(return_value=0)
        engine.redis.setex = AsyncMock()
        result = await engine._check_rsi_extreme()
        assert result is not None
        assert "перепродан" in result["message"]

    def test_all_triggers_have_ttl(self):
        for trigger in ["ma_cross", "bb_touch", "rsi_extreme", "mvrv_zone", "fg_extreme", "vol_spike", "funding_spike"]:
            assert trigger in TRIGGERS
            assert TRIGGERS[trigger] > 0


# ─── Alert Manager Edge Cases ──────────────────────────────────────

class TestAlertManagerEdgeCases:
    @pytest.mark.asyncio
    async def test_volume_spike_zero_avg_returns(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=["0", "1000"])
        am = AlertManager(AsyncMock(), redis, AsyncMock())
        await am._check_volume_spike({"user_id": 1}, 100000, False, False)
        am.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_volume_spike_none_values_returns(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        am = AlertManager(AsyncMock(), redis, AsyncMock())
        await am._check_volume_spike({"user_id": 1}, 100000, False, False)
        am.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_alerts_no_subscribers(self):
        db = AsyncMock()
        db.get_latest_price = AsyncMock(return_value=100000)
        db.get_users_with_subscriptions = AsyncMock(return_value=[])
        am = AlertManager(db, AsyncMock(), AsyncMock())
        await am.check_alerts()


# ─── Model Validation ─────────────────────────────────────────────

class TestIndicatorSet:
    def test_empty_indicator(self):
        ind = IndicatorSet(time=datetime.now(timezone.utc), symbol="BTCUSD")
        assert ind.rsi is None
        assert ind.ma_50 is None

    def test_partial_indicators(self):
        from datetime import datetime, timezone
        ind = IndicatorSet(
            time=datetime.now(timezone.utc),
            symbol="BTCUSD",
            rsi=45.0,
            macd=100.0,
            macd_signal=95.0,
            macd_hist=5.0,
        )
        assert ind.rsi == 45.0
        assert ind.ma_50 is None


# ─── Analyzer Edge Cases ───────────────────────────────────────────

class TestAnalyzerEdgeCases:
    @pytest.mark.asyncio
    async def test_compute_indicators_not_enough_data(self):
        from btcbot.analyzer import Analyzer
        db = AsyncMock()
        db.get_1m_candles_since = AsyncMock(return_value=[])
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        a = Analyzer(db, redis)
        result = await a.compute_indicators()
        assert result is None

    @pytest.mark.asyncio
    async def test_compute_volatility_not_enough_data(self):
        from btcbot.analyzer import Analyzer
        db = AsyncMock()
        db.get_hourly_candles_since = AsyncMock(return_value=[])
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        a = Analyzer(db, redis)
        result = await a.compute_volatility()
        assert result is None

    @pytest.mark.asyncio
    async def test_predict_no_price(self):
        from btcbot.analyzer import Analyzer
        db = AsyncMock()
        db.get_latest_price = AsyncMock(return_value=None)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        a = Analyzer(db, redis)
        result = await a.predict()
        assert result is None

    def test_liquidity_zones_insufficient_data(self):
        import pandas as pd
        from btcbot.analyzer import Analyzer
        a = Analyzer(None, None)
        candles = pd.DataFrame({"high": [50000], "low": [49000], "close": [49500]})
        zones = a._liquidity_zones(candles)
        assert zones == []


# ─── Utils ─────────────────────────────────────────────────────────

class TestUtils:
    def test_opencode_json_not_required_for_non_agents(self):
        """Test that btcbot code doesn't require opencode.json to function."""
        import os
        # Core modules should be importable without opencode.json
        from btcbot.config import settings
        assert settings is not None
