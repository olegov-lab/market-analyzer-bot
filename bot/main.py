import asyncio
from datetime import datetime, timedelta, timezone

from aiogram.types import MenuButtonWebApp, WebAppInfo

from bot.state import bot, db, dp, redis_client, analyzer, _ts
from bot.handlers import alerts, ask, btc, game, info, learn, news, price_alerts
from btcbot.config import settings
from btcbot.news import build_market_brain_comment, fetch_news


@dp.startup()
async def on_startup():
    await db.connect()

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📊 BTC",
                web_app=WebAppInfo(url=settings.miniapp_url),
            )
        )
    except Exception as e:
        print(f"Failed to set menu button: {e}")

    asyncio.create_task(analyzer.warmup_cache())


@dp.shutdown()
async def on_shutdown():
    await db.close()
    if redis_client:
        await redis_client.aclose()


async def _daily_news():
    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        sleep_sec = (target - now).total_seconds()
        await asyncio.sleep(sleep_sec)

        try:
            articles = await fetch_news(redis_client)
            if not articles:
                continue

            bull_count = sum(1 for a in articles if a.get("sentiment") == "bullish")
            bear_count = sum(1 for a in articles if a.get("sentiment") == "bearish")
            total = len(articles)

            mood = "🟢 бычье" if bull_count > bear_count else "🔴 медвежье" if bear_count > bull_count else "🟡 нейтральное"
            worry = bear_count / total if total else 0
            worry_label = "🔴 высокий" if worry >= 0.6 else "🟡 средний" if worry >= 0.3 else "🟢 низкий"

            lines = ["☀️ *BTC Monitor* · Доброе утро!", "", _ts(), ""]
            lines.append("📊 Ежедневный дайджест новостей Bitcoin")
            lines.append("")
            lines.append(f"▸ **Настроение:** {mood}")
            lines.append(f"▸ **Бычьих:** {bull_count}  **Медвежьих:** {bear_count}")
            lines.append(f"▸ **Тревога:** {worry_label}")
            lines.append("")

            emoji_map = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
            for a in articles:
                sentiment = a.get("sentiment", "neutral")
                emoji = emoji_map.get(sentiment, "🟡")
                src = a.get("source", "")
                src_part = f" — {src}" if src else ""
                lines.append(f"{emoji} [{a['title']}]({a['url']}){src_part}")

            lines.append("")
            lines.append(f"💬 **Аналитик рынка:** {build_market_brain_comment(bull_count, bear_count, total)}")
            lines.append("")
            lines.append("♻️ Завтра в 10:00 UTC · `/news` в любое время")
            msg = "\n".join(lines)

            users = await db.get_active_users()
            sent = 0
            for u in users:
                try:
                    await bot.send_message(u["user_id"], msg, parse_mode="Markdown", disable_web_page_preview=True)
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            print(f"Daily news sent to {sent}/{len(users)} users")
        except Exception as e:
            print(f"Daily news broadcast failed: {e}")


async def main():
    asyncio.create_task(_daily_news())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
