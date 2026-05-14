import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from btcbot.alerts import AlertManager, COOLDOWN_MINUTES


class TestAlertManager:
    def make_alert_manager(self, bot=None):
        db = AsyncMock()
        redis = AsyncMock()
        bot = bot or AsyncMock()
        am = AlertManager(db, redis, bot)
        am.db = db
        am.redis = redis
        am.bot = bot
        return am

    def test_cooldown_key_format(self):
        am = self.make_alert_manager()
        key = am._cooldown_key(123, "rsi")
        assert key == "123:rsi"

    def test_no_cooldown_initially(self):
        am = self.make_alert_manager()
        assert not am._is_on_cooldown(123, "rsi")

    def test_cooldown_after_set(self):
        am = self.make_alert_manager()
        am._set_cooldown(123, "rsi")
        assert am._is_on_cooldown(123, "rsi")

    def test_different_alert_types_independent(self):
        am = self.make_alert_manager()
        am._set_cooldown(123, "rsi")
        assert not am._is_on_cooldown(123, "ma_cross")

    @pytest.mark.asyncio
    async def test_check_alerts_no_price(self):
        am = self.make_alert_manager()
        am.db.get_latest_price = AsyncMock(return_value=None)
        await am.check_alerts()
        am.db.get_users_with_subscriptions.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_alerts_with_no_users(self):
        am = self.make_alert_manager()
        am.db.get_latest_price = AsyncMock(return_value=100000.0)
        am.db.get_users_with_subscriptions = AsyncMock(return_value=[])
        await am.check_alerts()

    @pytest.mark.asyncio
    async def test_rsi_alert_oversold(self):
        am = self.make_alert_manager()
        am._get_indicators = AsyncMock(return_value={"rsi": 25.0})
        am._send_alert = AsyncMock()

        user = {"user_id": 1}
        await am._check_rsi_alert(user, 100000)

        am._send_alert.assert_called_once()
        args = am._send_alert.call_args[0]
        assert args[1] == "rsi"
        assert "oversold" in args[3].lower()

    @pytest.mark.asyncio
    async def test_rsi_alert_overbought(self):
        am = self.make_alert_manager()
        am._get_indicators = AsyncMock(return_value={"rsi": 75.0})
        am._send_alert = AsyncMock()

        user = {"user_id": 2}
        await am._check_rsi_alert(user, 100000)

        am._send_alert.assert_called_once()
        args = am._send_alert.call_args[0]
        assert "overbought" in args[3].lower()

    @pytest.mark.asyncio
    async def test_rsi_alert_mid_range_noop(self):
        am = self.make_alert_manager()
        am._get_indicators = AsyncMock(return_value={"rsi": 50.0})
        am._send_alert = AsyncMock()

        user = {"user_id": 3}
        await am._check_rsi_alert(user, 100000)
        am._send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_ma_cross_detection(self):
        am = self.make_alert_manager()
        # abs(95050-95000)/95000 = 50/95000 ≈ 0.000526 < 0.001 → triggers
        am._get_indicators = AsyncMock(return_value={"ma_50": 95050, "ma_200": 95000})
        am._send_alert = AsyncMock()

        user = {"user_id": 4}
        await am._check_ma_cross(user, 100000)
        am._send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_volume_spike_normal_threshold(self):
        am = self.make_alert_manager()
        am.redis.get = AsyncMock(side_effect=["1000", "3500"])
        am._send_alert = AsyncMock()

        user = {"user_id": 5}
        await am._check_volume_spike(user, 100000, False, False)
        am._send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_volume_spike_night_lower_threshold(self):
        am = self.make_alert_manager()
        am.redis.get = AsyncMock(side_effect=["1000", "2200"])
        am._send_alert = AsyncMock()

        user = {"user_id": 6}
        await am._check_volume_spike(user, 100000, False, True)
        am._send_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_volume_spike_below_threshold(self):
        am = self.make_alert_manager()
        am.redis.get = AsyncMock(side_effect=["1000", "2000"])
        am._send_alert = AsyncMock()

        user = {"user_id": 7}
        await am._check_volume_spike(user, 100000, False, False)
        am._send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_alert_on_cooldown_skips(self):
        am = self.make_alert_manager()
        am._set_cooldown(10, "rsi")
        am.bot.send_message = AsyncMock()

        await am._send_alert(10, "rsi", 100000, "test")
        am.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_alert_off_cooldown_sends(self):
        bot = AsyncMock()
        am = self.make_alert_manager(bot=bot)
        am.db.pool = MagicMock()
        am.db.pool.execute = AsyncMock(return_value=None)

        await am._send_alert(99, "rsi", 100000, "test message")
        bot.send_message.assert_called_once()
        assert am._is_on_cooldown(99, "rsi")

    @pytest.mark.asyncio
    async def test_price_alert_above_triggers(self):
        bot = AsyncMock()
        am = self.make_alert_manager(bot=bot)
        am.db.get_latest_price = AsyncMock(return_value=105000)
        alerts = [{"id": 1, "user_id": 5, "target_price": 100000, "direction": "above"}]
        am.db.get_active_price_alerts = AsyncMock(return_value=alerts)
        am.db.mark_price_alert_triggered = AsyncMock()

        await am.check_price_alerts()
        bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_price_alert_below_not_triggered_when_above(self):
        bot = AsyncMock()
        am = self.make_alert_manager(bot=bot)
        am.db.get_latest_price = AsyncMock(return_value=90000)
        alerts = [{"id": 2, "user_id": 6, "target_price": 85000, "direction": "below"}]
        am.db.get_active_price_alerts = AsyncMock(return_value=alerts)

        await am.check_price_alerts()
        bot.send_message.assert_not_called()
