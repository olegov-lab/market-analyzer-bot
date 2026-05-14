import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from btcbot.game import GameEngine


def _make_user_row(**overrides):
    defaults = {
        "balance": 10000.0,
        "total_pnl": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
    }
    defaults.update(overrides)
    return defaults


def _make_position_row(**overrides):
    defaults = {
        "id": 1,
        "side": "LONG",
        "entry_price": 95000.0,
        "quantity": 0.01,
        "notional": 950.0,
        "opened_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return defaults


def _make_trade_row(**overrides):
    defaults = {
        "id": 1,
        "side": "LONG",
        "entry_price": 95000.0,
        "exit_price": 100000.0,
        "quantity": 0.01,
        "pnl": 50.0,
        "pnl_pct": 5.26,
        "closed_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return defaults


class TestGameEngine:
    def make_engine(self):
        db = AsyncMock()
        return GameEngine(db)

    @pytest.mark.asyncio
    async def test_buy_minimum_amount(self):
        engine = self.make_engine()
        user = _make_user_row(balance=100)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.get_positions = AsyncMock(return_value=[])
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.open_position = AsyncMock(return_value={"id": 1})

        result = await engine.buy(1, 10.0)
        assert result["side"] == "LONG"
        assert result["quantity"] > 0

    @pytest.mark.asyncio
    async def test_buy_below_minimum_raises(self):
        engine = self.make_engine()
        with pytest.raises(ValueError, match="Минимальная сумма"):
            await engine.buy(1, 5.0)

    @pytest.mark.asyncio
    async def test_buy_insufficient_balance_raises(self):
        engine = self.make_engine()
        user = _make_user_row(balance=5.0)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        with pytest.raises(ValueError, match="Недостаточно средств"):
            await engine.buy(1, 100.0)

    @pytest.mark.asyncio
    async def test_sell_no_positions_raises(self):
        engine = self.make_engine()
        engine.db.get_positions = AsyncMock(return_value=[])
        with pytest.raises(ValueError, match="Нет открытой позиции"):
            await engine.sell(1)

    @pytest.mark.asyncio
    async def test_get_portfolio_no_positions(self):
        engine = self.make_engine()
        user = _make_user_row()
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_positions = AsyncMock(return_value=[])
        engine.db.get_trades = AsyncMock(return_value=[])

        result = await engine.get_portfolio(1)
        assert result["balance"] == 10000.0
        assert result["total_value"] == 10000.0
        assert result["positions"] == []

    @pytest.mark.asyncio
    async def test_get_portfolio_with_long_position(self):
        engine = self.make_engine()
        user = _make_user_row(balance=9000.0)
        pos = _make_position_row(entry_price=95000, quantity=0.01, notional=950)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_positions = AsyncMock(return_value=[pos])
        engine.db.get_trades = AsyncMock(return_value=[])

        result = await engine.get_portfolio(1)
        assert result["unrealized_pnl"] == 50.0
        assert result["total_value"] == 10000.0

    @pytest.mark.asyncio
    async def test_get_portfolio_win_rate(self):
        engine = self.make_engine()
        user = _make_user_row(total_trades=10, winning_trades=7)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_positions = AsyncMock(return_value=[])
        engine.db.get_trades = AsyncMock(return_value=[])

        result = await engine.get_portfolio(1)
        assert result["win_rate"] == 70.0

    @pytest.mark.asyncio
    async def test_get_portfolio_zero_trades_win_rate(self):
        engine = self.make_engine()
        user = _make_user_row(total_trades=0, winning_trades=0)
        engine.db.get_or_create_game_user = AsyncMock(return_value=user)
        engine.db.get_latest_price = AsyncMock(return_value=100000.0)
        engine.db.get_positions = AsyncMock(return_value=[])
        engine.db.get_trades = AsyncMock(return_value=[])

        result = await engine.get_portfolio(1)
        assert result["win_rate"] == 0

    def test_compute_league_bronze(self):
        league = GameEngine.compute_league(-50.0)
        assert league["league"] == "bronze"

    def test_compute_league_silver(self):
        league = GameEngine.compute_league(500.0)
        assert league["league"] == "silver"

    def test_compute_league_gold(self):
        league = GameEngine.compute_league(2000.0)
        assert league["league"] == "gold"

    def test_compute_league_platinum(self):
        league = GameEngine.compute_league(10000.0)
        assert league["league"] == "platinum"

    def test_constants(self):
        assert GameEngine.MIN_TRADE_USDT == 10.0
        assert GameEngine.STARTING_BALANCE == 10000.0
        assert GameEngine.FEE_PCT == 0.001
