import asyncio
import json
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from btcbot.analyzer import Analyzer
from btcbot.alerts import AlertManager
from btcbot.breakout import ProactiveAlertEngine, TRIGGERS
from btcbot.config import settings
from btcbot.db import Database


class Scheduler:
    def __init__(self, analyzer: Analyzer, alert_manager: AlertManager, proactive: ProactiveAlertEngine | None = None) -> None:
        self.scheduler = AsyncIOScheduler()
        self.analyzer = analyzer
        self.alert_manager = alert_manager
        self.proactive = proactive

    def start(self) -> None:
        self.scheduler.add_job(
            self._analyze_and_alert,
            CronTrigger(minute="*/15", hour="6-21"),
            id="day_analysis",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._analyze_and_alert,
            CronTrigger(minute="0", hour="22-23,0-5"),
            id="night_analysis",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._compute_indicators,
            CronTrigger(minute="*/5"),
            id="indicators",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._make_prediction,
            CronTrigger(minute="0", hour="*/1"),
            id="prediction",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._retrain_model,
            CronTrigger(day_of_week="mon", hour="3", minute="0"),
            id="retrain_model",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._make_prediction_1w,
            CronTrigger(hour="0,6,12,18", minute="0"),
            id="prediction_1w",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._check_price_alerts,
            CronTrigger(minute="*/5"),
            id="price_alerts",
            replace_existing=True,
        )
        if self.proactive:
            self.scheduler.add_job(
                self._check_proactive_triggers,
                CronTrigger(minute="*/2"),
                id="proactive",
                replace_existing=True,
            )
        self.scheduler.add_job(
            self._generate_daily_story,
            CronTrigger(hour="9", minute="0"),
            id="daily_story",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._resolve_price_guesses,
            CronTrigger(hour="0", minute="5"),
            id="resolve_guesses",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    async def _analyze_and_alert(self) -> None:
        await self.alert_manager.check_alerts()

    async def _compute_indicators(self) -> None:
        indicators = await self.analyzer.compute_indicators()
        if indicators:
            redis = self.analyzer.redis
            data = indicators.model_dump(mode="json")
            await redis.set("btc:indicators", json.dumps(data))
            await redis.publish("btc:indicators", json.dumps(data))

    async def _make_prediction(self) -> None:
        await self.analyzer.predict()

    async def _retrain_model(self) -> None:
        logger.info("Starting weekly model retraining")
        try:
            Analyzer._lgb_model = None
            await self.analyzer.predict()
            logger.info("Model retraining completed")
        except Exception as e:
            logger.error("Model retraining failed: {}", e)

    async def _check_price_alerts(self) -> None:
        await self.alert_manager.check_price_alerts()

    async def _check_proactive_triggers(self) -> None:
        if not self.proactive:
            return
        results = await self.proactive.check_all()
        for r in results:
            trigger = r["trigger"]
            msg = r["message"]
            if await self.proactive._is_cooldown(trigger):
                continue
            await self.proactive._queue_alert(trigger, msg)
            ttl = TRIGGERS.get(trigger, 7200)
            await self.proactive._set_cooldown(trigger, ttl)
            logger.info("Proactive alert queued: {} — {}", trigger, msg[:80])

    async def _generate_daily_story(self) -> None:
        try:
            from btcbot.daily_story import generate_daily_story
            story = await generate_daily_story(self.analyzer.db, self.analyzer.redis, self.analyzer)
            key = "btc:daily:story:queue"
            raw = await self.analyzer.redis.get(key)
            events = json.loads(raw) if raw else []
            events.append(story)
            if len(events) > 3:
                events = events[-3:]
            await self.analyzer.redis.set(key, json.dumps(events, ensure_ascii=False))
            logger.info("Daily story generated")
        except Exception as e:
            logger.error(f"Daily story generation failed: {e}")

    async def _resolve_price_guesses(self) -> None:
        logger.info("Resolving daily price guesses...")
        try:
            price = await self.analyzer.db.get_latest_price("BTCUSD")
            if price:
                results = await self.analyzer.db.resolve_guesses(price)
                if results:
                    winners = [r for r in results if r.get("won")]
                    for w in winners:
                        logger.info(f"Guess winner: user {w['user_id']} won {w['stars_won']} stars")
        except Exception as e:
            logger.error(f"Guess resolution failed: {e}")

    async def _make_prediction_1w(self) -> None:
        logger.info("Computing weekly on-chain prediction")
        try:
            score = await self.analyzer._predict_1w("BTCUSD")
            if score:
                redis = self.analyzer.redis
                await redis.set("btc:onchain:cycle_phase", score.cycle_phase)
                await redis.set("btc:onchain:cycle_score", str(score.cycle_score))
                logger.info("1W prediction: {} (score: {})", score.cycle_phase, score.cycle_score)
        except Exception as e:
            logger.error("1W prediction failed: {}", e)


async def _auto_seed(db):
    try:
        from btcbot.seed_history import seed
        n = await seed(db, days=90)
        if n > 0:
            logger.info(f"Auto-seeded {n} historical prices, refreshing aggregates...")
            async with db.pool.acquire(timeout=5.0) as conn:
                await conn.execute("CALL refresh_continuous_aggregate('candles_1m', NULL, NULL)")
                await conn.execute("CALL refresh_continuous_aggregate('candles_4h', NULL, NULL)")
            logger.info("Continuous aggregates refreshed after seed")
    except Exception as e:
        logger.warning(f"Auto-seed skipped: {e}")


async def main() -> None:
    import redis.asyncio as aioredis
    from btcbot.alerts import AlertManager
    from aiogram import Bot

    db = Database(settings.database_url, pool_min_size=settings.db_pool_min, pool_max_size=settings.db_pool_max)
    await db.connect()

    asyncio.create_task(_auto_seed(db))

    r = aioredis.from_url(settings.redis_url)
    bot = Bot(token=settings.telegram_bot_token)

    analyzer = Analyzer(db, r)
    alert_manager = AlertManager(db, r, bot)
    proactive = ProactiveAlertEngine(db, r)
    scheduler = Scheduler(analyzer, alert_manager, proactive)
    scheduler.start()

    async def _refresh_lb():
        while True:
            await asyncio.sleep(3600)
            try:
                await db.refresh_leaderboard()
            except Exception:
                pass
    asyncio.create_task(_refresh_lb())

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        scheduler.stop()
        await bot.session.close()
        await r.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
