from aiogram import F
from aiogram.filters import Command, or_f
from aiogram.types import Message

from btcbot.game import GameEngine
from btcbot.subscription import get_user_tier, Tier
from bot.state import db, dp, redis_client, _menu_kb, get_user_lang
from bot.i18n import t


game = GameEngine(db)


def _stars_bar(stars: int) -> str:
    filled = min(stars, 10)
    return "⭐" * filled + "☆" * (10 - filled)


@dp.message(Command(commands=["mine"]))
async def mine_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    try:
        result = await game.mine_click(uid, redis_client)
        await message.answer(
            f"⛏ <b>Mining</b>\n\n"
            f"▸ Mined: +{result['earned']} satoshi\n"
            f"▸ Total: {result['total_sats']} satoshi\n"
            f"▸ Streak: {result['streak']} days (x{result['streak_mult']})\n"
            f"▸ Referral bonus: x{result['ref_mult']}\n"
            f"▸ ⭐: {result['stars']}",
            parse_mode="HTML",
            reply_markup=_menu_kb(lang),
        )
    except ValueError as e:
        await message.answer(f"⛏ {e}", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["roulette"]))
async def roulette_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    parts = message.text.split()
    bet = int(parts[1]) if len(parts) > 1 else 1
    try:
        result = await game.roulette_spin(uid, bet, redis_client)
        if result["won"]:
            await message.answer(
                f"{result['emoji']} <b>Roulette</b>\n\n"
                f"▸ Bet: {result['bet']} ⭐\n"
                f"▸ Multiplier: x{result['multiplier']}\n"
                f"▸ Win: +{result['win']} ⭐\n"
                f"▸ Net: +{result['net']} ⭐",
                parse_mode="HTML",
                reply_markup=_menu_kb(lang),
            )
        else:
            await message.answer(
                f"{result['emoji']} <b>Roulette</b>\n\n"
                f"▸ Bet: {result['bet']} ⭐\n"
                f"▸ Multiplier: x{result['multiplier']}\n"
                f"▸ Loss: -{result['bet']} ⭐",
                parse_mode="HTML",
                reply_markup=_menu_kb(lang),
            )
    except ValueError as e:
        await message.answer(f"🎰 {e}", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["guess"]))
async def guess_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    parts = message.text.split()
    if len(parts) < 2:
        state = await game.get_guess_state(uid)
        if state["today_guess"]:
            await message.answer(
                f"🎯 <b>Price Guess</b>\n\n"
                f"▸ Your guess: ${state['today_guess']['guess_price']:,.0f}\n"
                f"▸ Current BTC: ${state['btc_price']:,.0f}\n"
                f"▸ ⭐: {_stars_bar(state['stars'])}\n\n"
                f"Results tomorrow at 00:00 UTC.",
                parse_mode="HTML",
                reply_markup=_menu_kb(lang),
            )
        else:
            await message.answer(
                f"🎯 <b>Price Guess</b>\n\n"
                f"Guess BTC price for tomorrow at 00:00 UTC!\n\n"
                f"▸ /guess <price> — make a guess\n"
                f"▸ Error < 1% → +5 ⭐\n"
                f"▸ Error < 3% → +2 ⭐\n"
                f"▸ Current BTC: ${state['btc_price']:,.0f}",
                parse_mode="HTML",
                reply_markup=_menu_kb(lang),
            )
        return
    try:
        guess_price = float(parts[1])
        result = await game.submit_guess(uid, guess_price)
        await message.answer(
            f"🎯 <b>Price Guess</b>\n\n"
            f"▸ Your guess: ${result['guess_price']:,.0f}\n"
            f"▸ BTC now: ${result['btc_price']:,.0f}\n"
            f"▸ Date: {result['guess_date']}\n\n"
            f"Waiting for results at 00:00 UTC! 🤞",
            parse_mode="HTML",
            reply_markup=_menu_kb(lang),
        )
    except ValueError as e:
        await message.answer(f"🎯 {e}", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["achievements"]))
async def achievements_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    state = await game.get_achievements_state(uid)
    parts = [f"🏆 <b>Achievements</b> ({state['unlocked']}/{state['total']})", ""]
    for a in state["list"]:
        icon = a["icon"] if a["unlocked"] else "🔒"
        name = a["name"] if a["unlocked"] else f"??? ({a['category']})"
        parts.append(f"{icon} {name} — {a['description']}")
    if not state["list"]:
        parts.append("No achievements yet. Trade, mine and guess the price!")
    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=_menu_kb(lang))


async def _check_trade_limit(user_id: int, msg_func) -> bool:
    return True


@dp.message(Command(commands=["buy"]))
async def buy_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    if not await _check_trade_limit(uid, message.answer):
        return
    parts = message.text.split()
    usdt = float(parts[1]) if len(parts) > 1 else 100
    try:
        result = await game.buy(uid, usdt)
        await message.answer(
            f"✅ <b>BTC Bought</b>\n\n"
            f"▪ {result['quantity']:.6f} BTC\n"
            f"▪ Entry: ${result['entry_price']:,.2f}\n"
            f"▪ Amount: ${result['notional']:,.2f}\n"
            f"▪ Fee: ${result['fee']:,.2f}",
            parse_mode="HTML",
            reply_markup=_menu_kb(lang),
        )
    except ValueError as e:
        await message.answer(f"❌ {e}", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["sell"]))
async def sell_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    if not await _check_trade_limit(uid, message.answer):
        return
    try:
        result = await game.sell(uid)
        emoji = "🎉" if result["is_win"] else "📉"
        sign = "+" if result["pnl"] >= 0 else ""
        await message.answer(
            f"{emoji} <b>Position Closed</b>\n\n"
            f"▪ Entry: ${result['entry_price']:,.2f}\n"
            f"▪ Exit: ${result['exit_price']:,.2f}\n"
            f"▪ Size: {result['quantity']:.6f} BTC\n"
            f"▪ P&amp;L: {sign}${result['pnl']:,.2f} ({result['pnl_pct']:+.2f}%)",
            parse_mode="HTML",
            reply_markup=_menu_kb(lang),
        )
    except ValueError as e:
        await message.answer(f"❌ {e}", reply_markup=_menu_kb(lang))


@dp.message(or_f(Command(commands=["portfolio"]), F.text == "🎮 Трейдинг"))
async def portfolio_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    await db.upsert_user(uid, message.from_user.username)
    tier = await get_user_tier(db, uid)
    p = await game.get_portfolio(uid)
    mining = await game.get_mining_state(uid, redis_client)

    badge = " 💎 PRO" if tier == Tier.PRO else " 👑 PRO+" if tier == Tier.PRO_PLUS else ""
    parts = [f"💰 <b>Portfolio{badge}</b>", ""]
    parts.append(f"▪ Value: ${p['total_value']:,.2f}")
    parts.append(f"▪ Cash: ${p['balance']:,.2f}")
    sign = "+" if p["total_pnl"] >= 0 else ""
    parts.append(f"▪ P&amp;L: {sign}${p['total_pnl']:,.2f}")
    parts.append(f"▪ Trades: {p['total_trades']} | Win: {p['win_rate']}%")
    parts.append(f"⛏ Mining streak: {mining['streak']} days | ⭐ {mining['stars']}")

    if p["positions"]:
        parts.append("")
        parts.append("── Open Positions ──")
        for pos in p["positions"]:
            pnl_sign = "+" if pos["pnl"] >= 0 else ""
            parts.append(f"▸ {pos['side']} {pos['quantity']:.6f} BTC @ ${pos['entry_price']:,.2f}")
            parts.append(f"  P&amp;L: {pnl_sign}${pos['pnl']:,.2f} ({pos['pnl_pct']:+.2f}%)")
    else:
        parts.append("")
        parts.append("💡 No open positions. /buy to start.")

    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=_menu_kb(lang))


@dp.message(Command(commands=["leaderboard"]))
async def leaderboard_cmd(message: Message):
    uid = message.from_user.id
    lang = await get_user_lang(uid)
    lb = await game.get_leaderboard()
    if not lb:
        await message.answer("🏆 No traders yet. Be the first: /buy", reply_markup=_menu_kb(lang))
        return

    parts = ["🏆 <b>Top Traders</b>", ""]
    for r in lb[:10]:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(r["rank"], f"#{r['rank']}")
        sign = "+" if r["total_pnl"] >= 0 else ""
        parts.append(f"{medal} {r['username'][:20]}: {sign}${r['total_pnl']:,.2f} ({r['total_trades']} trades)")

    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=_menu_kb(lang))
