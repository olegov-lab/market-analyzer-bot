import json
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger


TRIGGERS = {
    "ma_cross": 86400,
    "bb_touch": 21600,
    "rsi_extreme": 14400,
    "mvrv_zone": 43200,
    "fg_extreme": 28800,
    "vol_spike": 7200,
    "funding_spike": 7200,
}


class ProactiveAlertEngine:
    def __init__(self, db: Any, redis_client: Any) -> None:
        self.db = db
        self.redis = redis_client

    async def check_all(self) -> list[dict]:
        results = []
        checks = [
            self._check_ma_cross,
            self._check_bb_touch,
            self._check_rsi_extreme,
            self._check_mvrv_zone,
            self._check_fg_extreme,
            self._check_vol_spike,
            self._check_funding_spike,
        ]
        for check in checks:
            try:
                result = await check()
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"Proactive check {check.__name__} failed: {e}")
        return results

    async def _read_indicators(self) -> Optional[dict]:
        raw = await self.redis.get("btc:indicators")
        if raw:
            return json.loads(raw)
        return None

    async def _read_price(self) -> Optional[float]:
        raw = await self.redis.get("btc:price")
        if raw:
            return float(raw)
        return None

    async def _is_cooldown(self, trigger: str) -> bool:
        key = f"btc:proactive:cooldown:{trigger}"
        return bool(await self.redis.exists(key))

    async def _set_cooldown(self, trigger: str, ttl: int) -> None:
        key = f"btc:proactive:cooldown:{trigger}"
        await self.redis.setex(key, ttl, "1")

    async def _queue_alert(self, trigger: str, message: str) -> None:
        events = []
        raw = await self.redis.get("btc:proactive:queue")
        if raw:
            events = json.loads(raw)
        events.append({
            "trigger": trigger,
            "message": message,
            "time": datetime.now(timezone.utc).isoformat(),
        })
        if len(events) > 50:
            events = events[-50:]
        await self.redis.set("btc:proactive:queue", json.dumps(events, ensure_ascii=False))

    async def _check_ma_cross(self) -> Optional[dict]:
        trigger = "ma_cross"
        if await self._is_cooldown(trigger):
            return None
        ind = await self._read_indicators()
        if not ind or not ind.get("ma_50") or not ind.get("ma_200"):
            return None
        price = await self._read_price()
        if not price:
            return None
        prev_state = await self.redis.get("btc:ma_cross:state")
        above = price > ind["ma_200"]
        new_state = "above" if above else "below"
        if prev_state and (prev_state.decode() if isinstance(prev_state, bytes) else prev_state) == new_state:
            return None
        await self.redis.set("btc:ma_cross:state", new_state)
        if prev_state is None:
            return None
        await self._set_cooldown(trigger, TRIGGERS[trigger])
        if new_state == "above":
            msg = f"🚨 MA50 пересекла MA200 снизу вверх (Golden Cross)\n💰 BTC: ${price:,.0f}\n📊 MA50: ${ind['ma_50']:,.0f} > MA200: ${ind['ma_200']:,.0f}"
        else:
            msg = f"🚨 MA50 пересекла MA200 сверху вниз (Death Cross)\n💰 BTC: ${price:,.0f}\n📊 MA50: ${ind['ma_50']:,.0f} < MA200: ${ind['ma_200']:,.0f}"
        return {"trigger": trigger, "message": msg}

    async def _check_bb_touch(self) -> Optional[dict]:
        trigger = "bb_touch"
        if await self._is_cooldown(trigger):
            return None
        ind = await self._read_indicators()
        if not ind or not ind.get("bb_upper") or not ind.get("bb_lower"):
            return None
        price = await self._read_price()
        if not price:
            return None
        bbu, bbl = ind["bb_upper"], ind["bb_lower"]
        if price >= bbu * 0.995:
            msg = f"🚨 Цена у верхней полосы Боллинджера\n💰 BTC: ${price:,.0f}\n📊 BB: ${bbl:,.0f} / ${ind.get('bb_middle', 0):,.0f} / ${bbu:,.0f}\n⚠️ Возможна коррекция"
        elif price <= bbl * 1.005:
            msg = f"🚨 Цена у нижней полосы Боллинджера\n💰 BTC: ${price:,.0f}\n📊 BB: ${bbl:,.0f} / ${ind.get('bb_middle', 0):,.0f} / ${bbu:,.0f}\n⚠️ Возможен отскок"
        else:
            return None
        await self._set_cooldown(trigger, TRIGGERS[trigger])
        return {"trigger": trigger, "message": msg}

    async def _check_rsi_extreme(self) -> Optional[dict]:
        trigger = "rsi_extreme"
        if await self._is_cooldown(trigger):
            return None
        ind = await self._read_indicators()
        if not ind or ind.get("rsi") is None:
            return None
        rsi = ind["rsi"]
        price = await self._read_price()
        if rsi >= 75:
            msg = f"🚨 RSI в зоне перекупленности\n📊 RSI(14): {rsi:.1f} (>75)\n💰 BTC: ${price:,.0f}" if price else f"🚨 RSI в зоне перекупленности\n📊 RSI(14): {rsi:.1f} (>75)"
        elif rsi <= 25:
            msg = f"🚨 RSI в зоне перепроданности\n📊 RSI(14): {rsi:.1f} (<25)\n💰 BTC: ${price:,.0f}" if price else f"🚨 RSI в зоне перепроданности\n📊 RSI(14): {rsi:.1f} (<25)"
        else:
            return None
        await self._set_cooldown(trigger, TRIGGERS[trigger])
        return {"trigger": trigger, "message": msg}

    async def _check_mvrv_zone(self) -> Optional[dict]:
        trigger = "mvrv_zone"
        if await self._is_cooldown(trigger):
            return None
        try:
            rows = await self.db.get_onchain_metric_since(
                "mvrv_z_score",
                datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
            )
            if not rows:
                return None
            mvrv = float(rows[-1]["value"])
            if mvrv >= 5:
                msg = f"🚨 MVRV Z-Score: {mvrv:.2f} — рынок экстремально переоценён\n⚠️ Исторически — зона коррекции"
            elif mvrv <= 0.3:
                msg = f"🚨 MVRV Z-Score: {mvrv:.2f} — рынок экстремально недооценён\n🟢 Исторически — зона накопления"
            else:
                return None
            await self._set_cooldown(trigger, TRIGGERS[trigger])
            return {"trigger": trigger, "message": msg}
        except Exception:
            return None

    async def _check_fg_extreme(self) -> Optional[dict]:
        trigger = "fg_extreme"
        if await self._is_cooldown(trigger):
            return None
        raw = await self.redis.get("fear_greed")
        if not raw:
            return None
        fg = json.loads(raw)
        val = fg.get("value", 50)
        if val <= 20:
            msg = f"🚨 Fear & Greed: {val}/100 — экстремальный страх\n🟢 Исторически — момент накопления"
        elif val >= 80:
            msg = f"🚨 Fear & Greed: {val}/100 — экстремальная жадность\n🔴 Исторически — сигнал осторожности"
        else:
            return None
        await self._set_cooldown(trigger, TRIGGERS[trigger])
        return {"trigger": trigger, "message": msg}

    async def _check_vol_spike(self) -> Optional[dict]:
        trigger = "vol_spike"
        if await self._is_cooldown(trigger):
            return None
        avg_raw = await self.redis.get("btc:volume:avg")
        cur_raw = await self.redis.get("btc:volume:current")
        if not avg_raw or not cur_raw:
            return None
        avg = float(avg_raw)
        cur = float(cur_raw)
        if avg <= 0 or cur / avg < 3:
            return None
        price = await self._read_price()
        msg = f"🚨 Всплеск объёма — {cur / avg:.1f}x среднего\n💰 BTC: ${price:,.0f}" if price else f"🚨 Всплеск объёма — {cur / avg:.1f}x среднего"
        await self._set_cooldown(trigger, TRIGGERS[trigger])
        return {"trigger": trigger, "message": msg}

    async def _check_funding_spike(self) -> Optional[dict]:
        trigger = "funding_spike"
        if await self._is_cooldown(trigger):
            return None
        try:
            rows = await self.db.get_onchain_metric_since(
                "funding_rate",
                datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0),
            )
            if not rows:
                return None
            fr = float(rows[-1]["value"])
            if fr > 0.03:
                msg = f"🚨 Funding Rate: {fr * 100:.2f}% — перегрев лонгов\n⚠️ Риск каскадной ликвидации"
            elif fr < -0.02:
                msg = f"🚨 Funding Rate: {fr * 100:.2f}% — перегрев шортов\n⚠️ Возможен short squeeze"
            else:
                return None
            await self._set_cooldown(trigger, TRIGGERS[trigger])
            return {"trigger": trigger, "message": msg}
        except Exception:
            return None
