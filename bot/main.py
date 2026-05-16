import asyncio
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonWebApp, WebAppInfo

from bot.state import bot, db, dp, redis_client, analyzer, _ts
from bot.handlers import alerts, ask, btc, game, info, learn, news, price_alerts, menu, subscribe, timezone
from btcbot.config import settings
from btcbot.news import build_market_brain_comment, fetch_news


@dp.startup()
async def on_startup():
    print("[DEBUG] on_startup: connecting to DB...")
    await db.connect()
    print("[DEBUG] on_startup: DB connected, setting menu button...")

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="btc", description="Цена и индикаторы"),
            BotCommand(command="predict", description="Прогноз BTC"),
            BotCommand(command="ask", description="AI-аналитик"),
            BotCommand(command="portfolio", description="Портфель и игры"),
            BotCommand(command="news", description="Пульс рынка"),
            BotCommand(command="learn", description="Азбука крипты"),
            BotCommand(command="subscribe", description="Уведомления"),
            BotCommand(command="alerts", description="Мои подписки"),
            BotCommand(command="timezone", description="Часовой пояс"),
            BotCommand(command="referral", description="Привести друга"),
            BotCommand(command="donate", description="Поддержать проект"),
            BotCommand(command="help", description="Помощь"),
        ], scope=BotCommandScopeDefault())
        print("[DEBUG] on_startup: commands set OK")
    except Exception as e:
        print(f"[DEBUG] on_startup: Failed to set commands: {e}")

    try:
        print(f"[DEBUG] on_startup: miniapp_url={settings.miniapp_url}")
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📊 BTC",
                web_app=WebAppInfo(url=settings.miniapp_url),
            )
        )
        print("[DEBUG] on_startup: menu button set OK")
    except Exception as e:
        print(f"[DEBUG] on_startup: Failed to set menu button: {e}")

    print("[DEBUG] on_startup: starting warmup_cache task...")
    asyncio.create_task(analyzer.warmup_cache())
    print("[DEBUG] on_startup: done")


@dp.shutdown()
async def on_shutdown():
    await db.close()
    if redis_client:
        await redis_client.aclose()


async def _daily_news():
    while True:
        now = datetime.now(dt_timezone.utc)
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


async def _proactive_consumer():
    queue_key = "btc:proactive:queue"
    await asyncio.sleep(30)
    while True:
        try:
            raw = await redis_client.get(queue_key)
            if raw:
                events = json.loads(raw)
                await redis_client.delete(queue_key)
                for ev in events:
                    trigger = ev["trigger"]
                    msg = ev["message"]
                    users = await db.get_active_users()
                    sent = 0
                    for u in users:
                        uid = u["user_id"]
                        ck = f"btc:proactive:sent:{trigger}:{uid}"
                        if await redis_client.exists(ck):
                            continue
                        try:
                            await bot.send_message(uid, msg)
                            await redis_client.setex(ck, 86400, "1")
                            sent += 1
                            await asyncio.sleep(0.05)
                        except Exception:
                            pass
                    if sent:
                        print(f"Proactive {trigger} sent to {sent} users")
        except Exception as e:
            print(f"Proactive consumer error: {e}")
        await asyncio.sleep(30)


async def _story_consumer():
    key = "btc:daily:story:queue"
    await asyncio.sleep(60)
    while True:
        try:
            raw = await redis_client.get(key)
            if raw:
                stories = json.loads(raw)
                await redis_client.delete(key)
                for story in stories:
                    users = await db.get_active_users()
                    sent = 0
                    for u in users:
                        try:
                            await bot.send_message(u["user_id"], story, parse_mode="Markdown")
                            sent += 1
                            await asyncio.sleep(0.05)
                        except Exception:
                            pass
                    if sent:
                        print(f"Daily story sent to {sent} users")
        except Exception as e:
            print(f"Story consumer error: {e}")
        await asyncio.sleep(120)


async def main():
    print("[DEBUG] main: starting background tasks...")
    asyncio.create_task(_daily_news())
    asyncio.create_task(_proactive_consumer())
    asyncio.create_task(_story_consumer())
    print("[DEBUG] main: starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
