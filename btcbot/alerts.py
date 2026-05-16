import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger

from btcbot.db import Database

COOLDOWN_MINUTES = 60


class AlertManager:
    def __init__(self, db: Database, redis_client: Any, bot: Any) -> None:
        self.db = db
        self.redis = redis_client
        self.bot = bot
        self._last_sent: dict[str, datetime] = {}

    def _cooldown_key(self, user_id: int, alert_type: str) -> str:
        return f"{user_id}:{alert_type}"

    def _is_on_cooldown(self, user_id: int, alert_type: str) -> bool:
        key = self._cooldown_key(user_id, alert_type)
        last = self._last_sent.get(key)
        if last is None:
            return False
        return datetime.now(timezone.utc) - last < timedelta(minutes=COOLDOWN_MINUTES)

    def _set_cooldown(self, user_id: int, alert_type: str) -> None:
        key = self._cooldown_key(user_id, alert_type)
        self._last_sent[key] = datetime.now(timezone.utc)

    async def check_alerts(self) -> None:
        price = await self.db.get_latest_price("BTCUSD")
        if not price:
            return

        now = datetime.now(timezone.utc)
        hour = now.hour

        rows = await self.db.get_users_with_subscriptions()
        users: dict[int, dict] = {}
        for row in rows:
            uid = row["user_id"]
            if uid not in users:
                users[uid] = {"user_id": uid, "timezone": row.get("timezone", "UTC"), "alert_types": set()}
            users[uid]["alert_types"].add(row["alert_type"])

        for user_data in users.values():
            for alert_type in user_data["alert_types"]:
                await self._check_alert(user_data, price, alert_type, hour)

    async def _check_alert(self, user: dict, price: float, alert_type: str, hour: int) -> None:
        is_night = hour < 6 or hour >= 22
        is_weekend = datetime.now(timezone.utc).weekday() >= 5

        if alert_type == "rsi":
            await self._check_rsi_alert(user, price)
        elif alert_type == "ma_cross":
            await self._check_ma_cross(user, price)
        elif alert_type == "volume_spike":
            await self._check_volume_spike(user, price, is_weekend, is_night)

    async def _get_indicators(self) -> dict:
        raw = await self.redis.get("btc:indicators")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {}

    async def _check_rsi_alert(self, user: dict, price: float) -> None:
        indicators = await self._get_indicators()
        rsi = indicators.get("rsi")
        if rsi is None:
            return
        if rsi < 30 or rsi > 70:
            direction = "oversold" if rsi < 30 else "overbought"
            msg = f"RSI = {rsi:.1f} — {direction}"
            await self._send_alert(user["user_id"], "rsi", price, msg)

    async def _check_ma_cross(self, user: dict, price: float) -> None:
        indicators = await self._get_indicators()
        ma50 = indicators.get("ma_50")
        ma200 = indicators.get("ma_200")
        if ma50 is None or ma200 is None:
            return
        if abs(ma50 - ma200) / ma200 < 0.001:
            cross_type = "golden" if ma50 > ma200 else "death"
            msg = f"MA50 ({ma50:.0f}) {cross_type} cross MA200 ({ma200:.0f})"
            await self._send_alert(user["user_id"], "ma_cross", price, msg)

    async def _check_volume_spike(self, user: dict, price: float, is_weekend: bool, is_night: bool) -> None:
        vol_str = await self.redis.get("btc:volume:avg")
        curr_vol_str = await self.redis.get("btc:volume:current")

        if not vol_str or not curr_vol_str:
            return
        try:
            avg_vol = float(vol_str)
            curr_vol = float(curr_vol_str)
        except (ValueError, TypeError):
            return

        if avg_vol <= 0:
            return

        threshold = 2.0 if (is_weekend or is_night) else 3.0
        if curr_vol > threshold * avg_vol:
            msg = f"Volume spike: {curr_vol:.0f} ({threshold}× avg {avg_vol:.0f})"
            await self._send_alert(user["user_id"], "volume_spike", price, msg)

    def _cleanup_cooldowns(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._last_sent.items() if now - v >= timedelta(minutes=COOLDOWN_MINUTES)]
        for k in expired:
            del self._last_sent[k]

    async def _send_alert(self, user_id: int, alert_type: str, price: float, message: str) -> None:
        if len(self._last_sent) > 10000:
            self._cleanup_cooldowns()
        if self._is_on_cooldown(user_id, alert_type):
            logger.debug("Alert {} for user {} on cooldown", alert_type, user_id)
            return
        self._set_cooldown(user_id, alert_type)
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ *{alert_type.upper()}*: {message}\n💰 ${price:,.0f}",
                parse_mode="Markdown",
            )
            await self.db.pool.execute(
                "INSERT INTO alerts (user_id, alert_type, price, message, sent) VALUES ($1,$2,$3,$4,TRUE)",
                user_id, alert_type, price, message,
            )
        except Exception as e:
            logger.error("Failed to send alert to {}: {}", user_id, e)

    async def check_price_alerts(self) -> None:
        price = await self.db.get_latest_price("BTCUSD")
        if not price:
            return

        alerts = await self.db.get_active_price_alerts()
        if not alerts:
            return

        for alert in alerts:
            should_trigger = False
            direction = alert["direction"]
            if direction == "above" and price >= alert["target_price"]:
                should_trigger = True
            elif direction == "below" and price <= alert["target_price"]:
                should_trigger = True
            elif direction == "any":
                should_trigger = True

            if should_trigger:
                await self._send_price_alert(alert, price)

    async def _send_price_alert(self, alert: dict, current_price: float) -> None:
        user_id = alert["user_id"]
        target = alert["target_price"]
        direction = alert["direction"]
        dir_emoji = "📈" if direction == "above" else "📉"
        dir_text = "выше" if direction == "above" else "ниже"
        direction_word = "пересёк" if direction == "any" else dir_text

        msg = (
            f"🚨 *Ценовой сигнал*\n"
            f"{dir_emoji} BTC {direction_word} ${target:,.0f}\n"
            f"💰 Текущая цена: ${current_price:,.0f}"
        )
        try:
            await self.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
            await self.db.mark_price_alert_triggered(alert["id"])
            logger.info("Price alert {} sent to user {}", alert["id"], user_id)
        except Exception as e:
            logger.error("Failed to send price alert {}: {}", alert["id"], e)
