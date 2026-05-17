import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from btcbot.game import GameEngine


def _make_user_row(**overrides):
    defaults = {
        "balance": 10000.0,
        "total_pnl": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "stars": 0,
    }
    defaults.update(overrides)
    return defaults


def _make_guess_row(**overrides):
    defaults = {
        "id": 1,
        "user_id": 1,
        "guess_date": "2026-05-15",
        "guess_price": 100000.0,
        "btc_price_at_resolution": 101000.0,
        "deviation_pct": 0.99,
        "won": False,
        "stars_won": 0,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return defaults


class TestPriceGuess:
    def make_engine(self):
        db = AsyncMock()
        return GameEngine(db)

    @pytest.mark.asyncio
    async def test_submit_guess_success(self):
        engine = self.make_engine()
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.submit_price_guess = AsyncMock(return_value={
            "guess_price": 101000.0, "guess_date": "2026-05-15"
        })
        result = await engine.submit_guess(1, 101000.0)
        assert result["guess_price"] == 101000.0
        assert result["btc_price"] == 100000.0

    @pytest.mark.asyncio
    async def test_submit_guess_zero_price_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="положительной"):
            await engine.submit_guess(1, 0)

    @pytest.mark.asyncio
    async def test_submit_guess_negative_price_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="положительной"):
            await engine.submit_guess(1, -100)

    @pytest.mark.asyncio
    async def test_submit_guess_no_price_raises(self):
        engine = self.make_engine()
        engine.db.get_latest_price = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="недоступна"):
            await engine.submit_guess(1, 100000)

    @pytest.mark.asyncio
    async def test_get_guess_state_no_guess(self):
        engine = self.make_engine()
        engine.db.get_user_guess_today = AsyncMock(return_value=None)
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_guess_history = AsyncMock(return_value=[])
        state = await engine.get_guess_state(1)
        assert state["today_guess"] is None
        assert state["btc_price"] == 100000.0
        assert state["history"] == []

    @pytest.mark.asyncio
    async def test_get_guess_state_with_guess(self):
        engine = self.make_engine()
        engine.db.get_user_guess_today = AsyncMock(return_value={"guess_price": 101000.0})
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_guess_history = AsyncMock(return_value=[
            _make_guess_row(guess_price=99000.0, deviation_pct=1.5, won=False, stars_won=0)
        ])
        state = await engine.get_guess_state(1)
        assert state["today_guess"]["guess_price"] == 101000.0
        assert len(state["history"]) == 1
        assert state["history"][0]["guess_price"] == 99000.0

    @pytest.mark.asyncio
    async def test_get_guess_state_with_winner(self):
        engine = self.make_engine()
        engine.db.get_user_guess_today = AsyncMock(return_value=None)
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_guess_history = AsyncMock(return_value=[
            _make_guess_row(guess_price=100500.0, deviation_pct=0.5, won=True, stars_won=50)
        ])
        state = await engine.get_guess_state(1)
        assert state["history"][0]["won"] is True
        assert state["history"][0]["stars_won"] == 50


class TestAchievements:
    def make_engine(self):
        db = AsyncMock()
        return GameEngine(db)

    @pytest.mark.asyncio
    async def test_unlock_new_achievement(self):
        engine = self.make_engine()
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "first_trade", "name": "Первая сделка", "icon": "🎯"
        })
        result = await engine.check_and_unlock(1, "first_trade")
        assert result["slug"] == "first_trade"
        assert result["name"] == "Первая сделка"

    @pytest.mark.asyncio
    async def test_unlock_duplicate_returns_none(self):
        engine = self.make_engine()
        engine.db.unlock_achievement = AsyncMock(return_value=None)
        result = await engine.check_and_unlock(1, "first_trade")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_achievements_state_all_locked(self):
        engine = self.make_engine()
        engine.db.get_user_achievements = AsyncMock(return_value=[
            {"slug": "first_trade", "name": "Первая сделка", "icon": "🎯",
             "category": "trader", "description": "desc", "unlocked_at": None},
            {"slug": "ten_trades", "name": "10 сделок", "icon": "📈",
             "category": "trader", "description": "desc", "unlocked_at": None},
        ])
        state = await engine.get_achievements_state(1)
        assert state["total"] == 2
        assert state["unlocked"] == 0
        assert state["list"][0]["unlocked"] is False

    @pytest.mark.asyncio
    async def test_get_achievements_state_partial(self):
        engine = self.make_engine()
        now = datetime.now(timezone.utc)
        engine.db.get_user_achievements = AsyncMock(return_value=[
            {"slug": "first_trade", "name": "Первая сделка", "icon": "🎯",
             "category": "trader", "description": "desc", "unlocked_at": now},
            {"slug": "ten_trades", "name": "10 сделок", "icon": "📈",
             "category": "trader", "description": "desc", "unlocked_at": None},
        ])
        state = await engine.get_achievements_state(1)
        assert state["total"] == 2
        assert state["unlocked"] == 1
        assert state["list"][0]["unlocked"] is True

    @pytest.mark.asyncio
    async def test_check_trade_achievements_first_trade(self):
        engine = self.make_engine()
        user = _make_user_row(total_trades=1, total_pnl=50.0, winning_trades=1)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "first_trade", "name": "Первая сделка", "icon": "🎯"
        })
        new = await engine.check_trade_achievements(1)
        assert len(new) == 1
        assert new[0]["slug"] == "first_trade"

    @pytest.mark.asyncio
    async def test_check_trade_achievements_no_new(self):
        engine = self.make_engine()
        user = _make_user_row(total_trades=0, total_pnl=0.0, winning_trades=0)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.unlock_achievement = AsyncMock(return_value=None)
        new = await engine.check_trade_achievements(1)
        assert new == []

    @pytest.mark.asyncio
    async def test_check_trade_achievements_multiple(self):
        engine = self.make_engine()
        user = _make_user_row(total_trades=50, total_pnl=5000.0, winning_trades=40)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        call_count = 0
        async def side_effect(uid, slug):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return {"slug": slug, "name": slug, "icon": "🎯"}
            return None
        engine.db.unlock_achievement = AsyncMock(side_effect=side_effect)
        new = await engine.check_trade_achievements(1)
        assert len(new) >= 3

    @pytest.mark.asyncio
    async def test_check_trade_achievements_platinum_league(self):
        engine = self.make_engine()
        user = _make_user_row(total_trades=100, total_pnl=15000.0, winning_trades=60)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "platinum_league", "name": "Платиновая лига", "icon": "💿"
        })
        new = await engine.check_trade_achievements(1)
        slugs = [a["slug"] for a in new]
        assert "platinum_league" in slugs

    @pytest.mark.asyncio
    async def test_check_guess_achievements_winner(self):
        engine = self.make_engine()
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "guess_winner", "name": "Победитель дня", "icon": "🏆"
        })
        new = await engine.check_guess_achievements(1, won=True)
        assert len(new) == 1
        assert new[0]["slug"] == "guess_winner"

    @pytest.mark.asyncio
    async def test_check_guess_achievements_streak(self):
        engine = self.make_engine()
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "guess_3_streak", "name": "3 дня прогнозов", "icon": "🔮"
        })
        engine.db.get_guess_history = AsyncMock(return_value=[
            _make_guess_row(), _make_guess_row(), _make_guess_row()
        ])
        new = await engine.check_guess_achievements(1, won=False)
        assert len(new) == 1
        assert new[0]["slug"] == "guess_3_streak"

    @pytest.mark.asyncio
    async def test_check_mining_achievements(self):
        engine = self.make_engine()
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "mining_1000", "name": "Майнер-любитель", "icon": "⛏"
        })
        new = await engine.check_mining_achievements(1, 1000)
        assert len(new) == 1
        assert new[0]["slug"] == "mining_1000"

    @pytest.mark.asyncio
    async def test_check_mining_achievements_both(self):
        engine = self.make_engine()
        call_count = 0
        async def side_effect(uid, slug):
            nonlocal call_count
            call_count += 1
            return {"slug": slug, "name": slug, "icon": "⛏"}
        engine.db.unlock_achievement = AsyncMock(side_effect=side_effect)
        new = await engine.check_mining_achievements(1, 10000)
        assert len(new) == 2

    @pytest.mark.asyncio
    async def test_check_referral_achievements(self):
        engine = self.make_engine()
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 5, "total_bonus": 25, "referrals": []
        })
        engine.db.unlock_achievement = AsyncMock(return_value={
            "slug": "referral_3", "name": "3 реферала", "icon": "👥"
        })
        new = await engine.check_referral_achievements(1)
        assert len(new) == 1
        assert new[0]["slug"] == "referral_3"

    @pytest.mark.asyncio
    async def test_empty_state(self):
        engine = self.make_engine()
        engine.db.get_user_achievements = AsyncMock(return_value=[])
        state = await engine.get_achievements_state(1)
        assert state["total"] == 0
        assert state["unlocked"] == 0
        assert state["list"] == []


class TestMining:
    def make_engine(self):
        db = AsyncMock()
        return GameEngine(db)

    def make_redis(self, initial_data=None):
        redis = AsyncMock()
        state = initial_data or {"earned": 0, "last_click": None, "streak": 0}
        redis.get = AsyncMock(return_value=json.dumps(state))
        redis.set = AsyncMock(return_value=True)
        return redis

    @pytest.mark.asyncio
    async def test_first_click(self):
        engine = self.make_engine()
        redis = self.make_redis()
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        result = await engine.mine_click(1, redis)
        assert result["total_sats"] > 0
        assert result["streak"] == 1
        assert result["stars"] == 0
        assert result["ref_mult"] == 1.0

    @pytest.mark.asyncio
    async def test_early_click_raises(self):
        engine = self.make_engine()
        from datetime import datetime, timezone
        recent = (datetime.now(timezone.utc)).isoformat()
        redis = self.make_redis({"earned": 10, "last_click": recent, "streak": 1})
        with pytest.raises(ValueError, match="Кулдаун"):
            await engine.mine_click(1, redis)

    @pytest.mark.asyncio
    async def test_streak_multiplier(self):
        engine = self.make_engine()
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        redis = self.make_redis({"earned": 50, "last_click": old, "streak": 5})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        result = await engine.mine_click(1, redis)
        assert result["streak"] == 6
        assert result["streak_mult"] > 1.0

    @pytest.mark.asyncio
    async def test_referral_multiplier(self):
        engine = self.make_engine()
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        redis = self.make_redis({"earned": 50, "last_click": old, "streak": 1})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 5, "total_bonus": 25, "referrals": []
        })
        result = await engine.mine_click(1, redis)
        assert result["ref_mult"] > 1.0

    @pytest.mark.asyncio
    async def test_stars_conversion(self):
        engine = self.make_engine()
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        redis = self.make_redis({"earned": 2500, "last_click": old, "streak": 2})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        result = await engine.mine_click(1, redis)
        assert result["total_sats"] > 2500
        assert result["stars"] >= 2

    @pytest.mark.asyncio
    async def test_streak_reset_after_24h(self):
        engine = self.make_engine()
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        redis = self.make_redis({"earned": 100, "last_click": old, "streak": 10})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        result = await engine.mine_click(1, redis)
        assert result["streak"] == 0

    @pytest.mark.asyncio
    async def test_get_mining_state_fresh(self):
        engine = self.make_engine()
        redis = self.make_redis()
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        state = await engine.get_mining_state(1, redis)
        assert state["total_sats"] == 0
        assert state["streak"] == 0
        assert state["can_mine"] is True
        assert state["stars"] == 0

    @pytest.mark.asyncio
    async def test_get_mining_state_on_cooldown(self):
        engine = self.make_engine()
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        redis = self.make_redis({"earned": 100, "last_click": recent, "streak": 3})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        state = await engine.get_mining_state(1, redis)
        assert state["can_mine"] is False
        assert state["cooldown_sec"] > 0
        assert state["total_sats"] == 100
        assert state["streak"] == 3

    @pytest.mark.asyncio
    async def test_get_mining_state_with_referrals(self):
        engine = self.make_engine()
        redis = self.make_redis({"earned": 500, "last_click": None, "streak": 0})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 3, "total_bonus": 15, "referrals": []
        })
        state = await engine.get_mining_state(1, redis)
        assert state["ref_mult"] == 1.3
        assert state["referrals"] == 3
        assert state["stars"] == 0

    @pytest.mark.asyncio
    async def test_empty_redis_state(self):
        engine = self.make_engine()
        redis = self.make_redis()
        redis.get = AsyncMock(return_value=None)
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        state = await engine.get_mining_state(1, redis)
        assert state["total_sats"] == 0
        assert state["can_mine"] is True

    @pytest.mark.asyncio
    async def test_sats_values_within_range(self):
        engine = self.make_engine()
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        redis = self.make_redis({"earned": 0, "last_click": old, "streak": 0})
        engine.db.get_referral_stats = AsyncMock(return_value={
            "count": 0, "total_bonus": 0, "referrals": []
        })
        results = set()
        for _ in range(20):
            redis.get = AsyncMock(return_value=json.dumps({"earned": 0, "last_click": old, "streak": 0}))
            r = await engine.mine_click(1, redis)
            results.add(r["earned"])
        assert any(50 <= v <= 160 for v in results)
