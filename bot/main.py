import asyncio
import json
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import MenuButtonWebApp, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from btcbot.analyzer import Analyzer
from btcbot.config import settings
from btcbot.db import Database
from btcbot.news import fetch_news, build_market_brain_comment, NEWS_CACHE_TTL


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("🕐 %-d %B %Y, %H:%M UTC")


def _rsi_bar(rsi: float) -> str:
    bar_len = 10
    filled = max(0, min(bar_len, int(rsi / 100 * bar_len)))
    bar = "▓" * filled + "░" * (bar_len - filled)
    color = "🟢" if rsi < 40 else "🟡" if rsi < 60 else "🔴"
    return f"{color} {bar} {rsi:.1f}"


def _greeting() -> str:
    h = datetime.now(timezone.utc).hour
    if 5 <= h < 12:
        return "Доброе утро"
    elif 12 <= h < 18:
        return "Добрый день"
    elif 18 <= h < 23:
        return "Добрый вечер"
    return "Доброй ночи"

menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/btc"), KeyboardButton(text="/predict")],
        [KeyboardButton(text="/subscribe"), KeyboardButton(text="/alerts")],
        [KeyboardButton(text="/news"), KeyboardButton(text="/learn")],
        [KeyboardButton(text="/help")],
    ],
    resize_keyboard=True,
)

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
db = Database(settings.database_url)
redis_client: aioredis.Redis = None
analyzer: Analyzer = None

with open("bot/lessons.json", encoding="utf-8") as f:
    LESSONS = json.load(f)


@dp.startup()
async def on_startup():
    global redis_client, analyzer
    await db.connect()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    analyzer = Analyzer(db, redis_client)

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📊 BTC",
                web_app=WebAppInfo(url=settings.miniapp_url),
            )
        )
    except Exception as e:
        print(f"Failed to set menu button: {e}")

    asyncio.create_task(_warmup_cache())


async def _warmup_cache():
    await asyncio.sleep(1)
    try:
        _ = await analyzer.compute_indicators()
        _ = await analyzer.predict()
        logger.info("Cache warmed up successfully")
    except Exception as e:
        logger.warning("Cache warmup incomplete: {}", e)


@dp.shutdown()
async def on_shutdown():
    await db.close()
    if redis_client:
        await redis_client.aclose()


@dp.message(Command(commands=["start"]))
async def start(message: types.Message):
    await db.upsert_user(message.from_user.id, message.from_user.username)
    articles = await fetch_news(redis_client)
    news_part = ""
    if articles:
        sent_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
        news_lines = []
        for a in articles[:3]:
            emoji = sent_emoji.get(a.get("sentiment", ""), "🟡")
            news_lines.append(f"{emoji} {a['title']}")
        news_part = "\n\n📰 *Последние новости:*\n" + "\n".join(news_lines) + "\n\n── Новости ──\n📢 `/news` — все новости"
    await message.answer(
        f"{_greeting()}! 🤖\n\n"
        "Я *BTC Monitor* — слежу за биткоином и помогаю понять, что происходит с ценой."
        f"{news_part}\n\n"
        "📊 Кнопка слева от ввода — Mini App с полной аналитикой\n\n"
        "💰 `/btc` — цена и индикаторы\n"
        "🔮 `/predict` — прогноз\n"
        "📖 `/learn` — азбука крипты\n"
        "📢 `/subscribe` — уведомления\n"
        "📰 `/news` — новости\n"
        "❌ `/alerts` — управление подписками\n"
        "❓ `/help` — помощь",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )


@dp.message(Command(commands=["btc"]))
async def btc(message: types.Message):
    indicators = await analyzer.compute_indicators()
    price = await db.get_latest_price("BTCUSD")

    if not price:
        await message.answer(f"❌ Нет данных о цене\n\n{_ts()}", parse_mode="Markdown", reply_markup=menu_kb)
        return

    pred = await analyzer.predict()

    sig_emoji = "🟢" if pred and pred.direction == "BUY" else "🔴" if pred and pred.direction == "SELL" else "⚪"
    sig_word = "BUY" if pred and pred.direction == "BUY" else "SELL" if pred and pred.direction == "SELL" else "HOLD"

    lines = [f"💰 *BTC Monitor* · Цена", "", _ts(), ""]
    lines.append(f"── {sig_emoji} 𝙎𝙄𝙂𝙉𝘼𝙇: {sig_word} {sig_emoji} ──")
    lines.append("")
    lines.append(f"▸ **BTC/USD:** ${price:,.0f}")

    if indicators:
        lines.append("")
        lines.append("── Технические ──")

        if indicators.rsi is not None:
            lines.append(f"▸ **RSI(14):** {_rsi_bar(indicators.rsi)}")
        else:
            lines.append(f"▸ **RSI(14):** ⏳")

        if indicators.bb_lower is not None and indicators.bb_middle is not None and indicators.bb_upper is not None:
            bb_pos = ""
            if price >= indicators.bb_upper * 0.99:
                bb_pos = " ← у верхней"
            elif price <= indicators.bb_lower * 1.01:
                bb_pos = " ← у нижней"
            lines.append(f"▸ **BB(20,2):** ${indicators.bb_lower:,.0f} / ${indicators.bb_middle:,.0f} / ${indicators.bb_upper:,.0f}{bb_pos}")

        if indicators.macd is not None:
            macd_dir = ""
            if indicators.macd_signal is not None:
                macd_dir = " · бычье" if indicators.macd > indicators.macd_signal else " · медвежье"
            sig = f"сигнал {indicators.macd_signal:+.1f}" if indicators.macd_signal is not None else ""
            hist = f"гистограмма {indicators.macd_hist:+.1f}" if indicators.macd_hist is not None else ""
            parts = [f"MACD {indicators.macd:+.1f}"]
            if sig:
                parts.append(sig)
            if hist:
                parts.append(hist)
            lines.append(f"▸ **{' · '.join(parts)}**{macd_dir}")

        ma_parts = []
        if indicators.ma_50 is not None:
            ma_parts.append(f"**MA50:** ${indicators.ma_50:,.0f}")
        else:
            ma_parts.append("**MA50:** ⏳ ~50 мин")
        if indicators.ma_100 is not None:
            ma_parts.append(f"**MA100:** ${indicators.ma_100:,.0f}")
        if indicators.ma_200 is not None:
            ma_parts.append(f"**MA200:** ${indicators.ma_200:,.0f}")
        else:
            ma_parts.append("**MA200:** ⏳ ~3.5 ч")
        lines.append(f"▸ {' | '.join(ma_parts)}")

    if pred and pred.meta:
        p1w = pred.meta.get("prediction_1w")
        if p1w and isinstance(p1w, dict) and p1w.get("mvrv_z") is not None:
            lines.append("")
            lines.append("── On-chain ──")
            mvrv = p1w.get("mvrv_z")
            mvrv_int = ""
            if mvrv < 0.5:
                mvrv_int = "недооценён"
            elif mvrv < 3.0:
                mvrv_int = "справедливая оценка"
            elif mvrv < 7.0:
                mvrv_int = "переоценён"
            else:
                mvrv_int = "экстремально переоценён"
            lines.append(f"▸ **MVRV Z-Score:** {mvrv:.2f} — {mvrv_int}")
            phase_label = {
                "ACCUMULATION": "накопление",
                "MARKUP": "рост",
                "DISTRIBUTION": "распределение",
                "MARKDOWN": "снижение",
            }
            phase = p1w.get("cycle_phase", "")
            score = p1w.get("cycle_score", 0)
            if phase:
                lines.append(f"▸ **Цикл:** {phase_label.get(phase, phase)} (score {score:+.2f})")
        else:
            lines.append("")
            lines.append("── On-chain ──")
            lines.append("⏳ данные появятся после настройки Glassnode API")

    lines.append("")
    lines.append("♻️ Обновление: реальное время")
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)


@dp.message(Command(commands=["predict"]))
async def predict(message: types.Message):
    price = await db.get_latest_price("BTCUSD")
    if not price:
        await message.answer(
            f"🔮 *BTC Monitor* · Прогноз\n\n⏳ данных пока нет, ожидаем 1–2 мин\n\n{_ts()}",
            parse_mode="Markdown",
            reply_markup=menu_kb,
        )
        return

    hours = await _estimate_hours(db, "BTCUSD")

    pred = await analyzer.predict()

    lines = [f"🔮 *BTC Monitor* · Прогноз", "", _ts(), ""]

    if pred:
        meta = pred.meta or {}
        p4h = meta.get("prediction_4h", {})
        p1w = meta.get("prediction_1w")
        plong = meta.get("prediction_long", {})

        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(pred.direction, "⚪")

        conf_pct = round(pred.confidence * 100)
        conf_color = "🟢" if conf_pct >= 70 else "🟡" if conf_pct >= 40 else "🔴"
        conf_label = "высокая" if conf_pct >= 70 else "средняя" if conf_pct >= 40 else "низкая"

        lines.append("")
        lines.append("── Сегодня ──")
        lines.append(f"{emoji} **{pred.direction}** · ${pred.price_min:,.0f}–${pred.price_max:,.0f}")
        lines.append(f"▸ **Уверенность:** {conf_color} {conf_pct}% — {conf_label}")

        zones = p4h.get("liquidity_zones", [])
        if zones:
            lines.append("")
            lines.append("── Риски ──")
            for z in zones:
                if z["type"] == "long":
                    lines.append(f"▸ откат до ${z['price']:,.0f} перед ростом")
                else:
                    lines.append(f"▸ пробой ${z['price']:,.0f} → цепная реакция вверх")

        if p1w and isinstance(p1w, dict) and p1w.get("cycle_phase"):
            lines.append("")
            lines.append("── Неделя ──")
            phase_label = {
                "ACCUMULATION": "накопление",
                "MARKUP": "рост",
                "DISTRIBUTION": "распределение",
                "MARKDOWN": "снижение",
            }
            phase_word = phase_label.get(p1w["cycle_phase"], "ожидание")
            week_parts = [f"{phase_word} (score {p1w.get('cycle_score', 0):+.2f})"]
            mvrv = p1w.get("mvrv_z")
            if mvrv is not None:
                week_parts.append(f"MVRV {mvrv:.1f}")
            sopr = p1w.get("sopr")
            if sopr is not None:
                week_parts.append(f"SOPR {sopr:.2f}")
            lines.append(f"▸ {', '.join(week_parts)}")
        elif hours >= 0.5:
            lines.append("")
            lines.append("── Неделя ──")
            lines.append("⏳ ждём on-chain данные (~24ч)")

        if plong and isinstance(plong, dict):
            long_parts = []
            if plong.get("price_vs_200w_ma_text"):
                txt = plong["price_vs_200w_ma_text"]
                txt = txt.replace("цена на ", "").replace("бычий тренд", "бычий").replace("медвежий тренд", "медвежий")
                long_parts.append(txt)
            hd = plong.get("halving_days")
            if hd is not None:
                long_parts.append(f"халвинг через {hd} дн")
            if long_parts:
                lines.append("")
                lines.append("── Долгосрочно ──")
                lines.append(f"▸ {', '.join(long_parts)}")

        lines.append("")
        lines.append("♻️ Обновление: прогноз — 1ч · on-chain — 6ч")
    else:
        lines.append("")
        lines.append("── Сегодня ──")
        lines.append("⏳ собираем историю для прогноза (~48ч)")
        lines.append("")
        lines.append("♻️ пришлю уведомление, когда прогноз будет готов")

    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=menu_kb)


async def _estimate_hours(db: Database, symbol: str) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = await db.get_1m_candles_since(symbol, since)
    if not rows:
        return 0.0
    times = [r["time"] for r in rows]
    span = (times[-1] - times[0]).total_seconds()
    return span / 3600


async def _estimate_ondays(db: Database) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=60)
    rows = await db.get_all_onchain_metrics_since(since)
    if not rows:
        return 0.0
    times = [r["time"] for r in rows]
    span = (times[-1] - times[0]).total_seconds()
    return span / 86400


@dp.message(Command(commands=["help"]))
async def help_cmd(message: types.Message):
    await message.answer(
        "🤖 *BTC Monitor* · Помощь\n\n"
        "📊 **Mini App** — кнопка слева от ввода (`📊 BTC`)\n\n"
        "💰 `/btc` — цена и индикаторы\n"
        "🔮 `/predict` — прогноз\n"
        "📖 `/learn` — азбука крипты\n"
        "📢 `/subscribe` — подписка на уведомления\n"
        "❌ `/alerts` — управление подписками\n"
        "📰 `/news` — новости Bitcoin\n\n"
        "♻️ Данные: Binance · Прогноз: 1ч / 6ч",
        parse_mode="Markdown",
        reply_markup=menu_kb,
    )


@dp.message(Command(commands=["subscribe"]))
async def subscribe(message: types.Message):
    builder = InlineKeyboardBuilder()
    for label, cb in [
        ("RSI — перекупленность/перепроданность", "sub_rsi"),
        ("MA Cross — пересечение MA50 и MA200", "sub_ma_cross"),
        ("Volume Spike — аномальный объём", "sub_volume_spike"),
    ]:
        builder.button(text=label, callback_data=cb)
    builder.adjust(1)
    await message.answer(
        "📢 *BTC Monitor* · Подписка\n\n"
        "Бот пришлёт уведомление при срабатывании:\n\n"
        "• **RSI** — перекупленность (>70) / перепроданность (<30)\n"
        "• **MA Cross** — пересечение MA50 и MA200\n"
        "• **Volume Spike** — объём > 3× среднего\n\n"
        "Выберите тип:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await message.answer("💡 Используй кнопки ниже", reply_markup=menu_kb)


@dp.message(Command(commands=["alerts"]))
async def alerts(message: types.Message):
    subs = await db.get_user_subscriptions(message.from_user.id)
    if not subs:
        await message.answer("🔔 *BTC Monitor* · Подписки\n\n❌ У вас нет активных подписок", parse_mode="Markdown", reply_markup=menu_kb)
        return

    builder = InlineKeyboardBuilder()
    for sub in subs:
        for at in sub["alert_types"]:
            builder.button(
                text=f"❌ {at} ({sub['symbol']})",
                callback_data=f"del_{sub['id']}_{at}",
            )
    builder.adjust(1)
    await message.answer(
        "🔔 *BTC Monitor* · Подписки\n\n💡 Нажмите ❌ чтобы отписаться:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@dp.callback_query(lambda c: c.data.startswith("sub_"))
async def handle_subscribe(callback: types.CallbackQuery):
    alert_type = callback.data.split("_", 1)[1]
    await db.upsert_user(callback.from_user.id, callback.from_user.username)
    await db.add_subscription(callback.from_user.id, "BTCUSD", "15m", [alert_type])
    await callback.answer("Подписка оформлена!")
    await callback.message.edit_text(f"✅ *BTC Monitor* · Подписка\n\n💡 Подписка на *{alert_type}* оформлена", parse_mode="Markdown")


@dp.callback_query(lambda c: c.data.startswith("del_"))
async def handle_delete(callback: types.CallbackQuery):
    parts = callback.data.split("_", 2)
    sub_id = int(parts[1])
    alert_type = parts[2] if len(parts) > 2 else ""
    if alert_type:
        await db.remove_alert_type(sub_id, alert_type)
    else:
        await db.delete_subscription(sub_id)
    await callback.answer("Подписка обновлена")
    await callback.message.edit_text("✅ *BTC Monitor* · Подписки\n\n💡 Подписка обновлена", parse_mode="Markdown")


@dp.message(Command(commands=["learn"]))
async def learn_cmd(message: types.Message):
    builder = InlineKeyboardBuilder()
    for lesson in LESSONS:
        builder.button(
            text=f"{lesson['id']}. {lesson['title']}",
            callback_data=f"lesson_{lesson['id']}",
        )
    builder.adjust(2)
    await message.answer(
        "📖 *BTC Monitor* · Азбука крипты\n\n"
        "10 коротких уроков для начинающих:\n\n"
        "• Как читать индикаторы\n"
        "• On-chain метрики\n"
        "• Анализ объёма\n\n"
        "Выберите урок:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await message.answer("💡 Используй кнопки ниже", reply_markup=menu_kb)


@dp.callback_query(lambda c: c.data.startswith("lesson_"))
async def show_lesson(callback: types.CallbackQuery):
    lesson_id = int(callback.data.split("_")[1])
    lesson = next((l for l in LESSONS if l["id"] == lesson_id), None)
    if not lesson:
        await callback.answer("Урок не найден")
        return

    builder = InlineKeyboardBuilder()
    if lesson_id > 1:
        builder.button(text="◀️", callback_data=f"lesson_{lesson_id - 1}")
    builder.button(text="📋", callback_data="learn_list")
    if lesson_id < len(LESSONS):
        builder.button(text="▶️", callback_data=f"lesson_{lesson_id + 1}")
    builder.adjust(3)

    await callback.message.edit_text(lesson["text"], reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(lambda c: c.data == "learn_list")
async def learn_list(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for lesson in LESSONS:
        builder.button(
            text=f"{lesson['id']}. {lesson['title']}",
            callback_data=f"lesson_{lesson['id']}",
        )
    builder.adjust(2)
    await callback.message.edit_text(
        "📖 *BTC Monitor* · Азбука крипты\n\n"
        "10 коротких уроков для начинающих:\n\n"
        "• Как читать индикаторы\n"
        "• On-chain метрики\n"
        "• Анализ объёма\n\n"
        "Выберите урок:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()





@dp.message(Command(commands=["news"]))
async def news_cmd(message: types.Message):
    articles = await fetch_news(redis_client)
    if not articles:
        await message.answer("Новостей пока нет", reply_markup=menu_kb)
        return

    bull_count = sum(1 for a in articles if a.get("sentiment") == "bullish")
    bear_count = sum(1 for a in articles if a.get("sentiment") == "bearish")
    total = len(articles)

    mood = "🟢 бычье" if bull_count > bear_count else "🔴 медвежье" if bear_count > bull_count else "🟡 нейтральное"

    worry = bear_count / total if total else 0
    worry_label = "🔴 высокий" if worry >= 0.6 else "🟡 средний" if worry >= 0.3 else "🟢 низкий"

    lines = ["📊 *BTC Monitor* · Пульс", "", _ts(), ""]
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
    lines.append("♻️ Обновление: новости — 5 мин")

    await message.answer("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=menu_kb)


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
