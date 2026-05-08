import asyncio
import json
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from btcbot.analyzer import Analyzer
from btcbot.alerts import AlertManager
from btcbot.config import settings
from btcbot.db import Database


class Scheduler:
    def __init__(self, analyzer: Analyzer, alert_manager: AlertManager) -> None:
        self.scheduler = AsyncIOScheduler()
        self.analyzer = analyzer
        self.alert_manager = alert_manager

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


async def main() -> None:
    import redis.asyncio as aioredis
    from btcbot.alerts import AlertManager
    from aiogram import Bot

    db = Database(settings.database_url)
    await db.connect()

    r = aioredis.from_url(settings.redis_url)
    bot = Bot(token=settings.telegram_bot_token)

    analyzer = Analyzer(db, r)
    alert_manager = AlertManager(db, r, bot)
    scheduler = Scheduler(analyzer, alert_manager)

    scheduler.start()

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        scheduler.stop()
        await bot.session.close()
        await r.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
