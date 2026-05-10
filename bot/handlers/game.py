from aiogram.filters import Command
from aiogram.types import Message

from btcbot.game import GameEngine
from bot.state import db, dp, menu_kb


game = GameEngine(db)


@dp.message(Command(commands=["buy"]))
async def buy_cmd(message: Message):
    uid = message.from_user.id
    await db.upsert_user(uid, message.from_user.username)
    parts = message.text.split()
    usdt = float(parts[1]) if len(parts) > 1 else 100
    try:
        result = await game.buy(uid, usdt)
        await message.answer(
            f"✅ <b>Куплено BTC</b>\n\n"
            f"▪ {result['quantity']:.6f} BTC\n"
            f"▪ Цена входа: ${result['entry_price']:,.2f}\n"
            f"▪ Сумма: ${result['notional']:,.2f}\n"
            f"▪ Комиссия: ${result['fee']:,.2f}",
            parse_mode="HTML",
            reply_markup=menu_kb,
        )
    except ValueError as e:
        await message.answer(f"❌ {e}", reply_markup=menu_kb)


@dp.message(Command(commands=["sell"]))
async def sell_cmd(message: Message):
    uid = message.from_user.id
    await db.upsert_user(uid, message.from_user.username)
    try:
        result = await game.sell(uid)
        emoji = "🎉" if result["is_win"] else "📉"
        sign = "+" if result["pnl"] >= 0 else ""
        await message.answer(
            f"{emoji} <b>Позиция закрыта</b>\n\n"
            f"▪ Вход: ${result['entry_price']:,.2f}\n"
            f"▪ Выход: ${result['exit_price']:,.2f}\n"
            f"▪ Объём: {result['quantity']:.6f} BTC\n"
            f"▪ P&amp;L: {sign}${result['pnl']:,.2f} ({result['pnl_pct']:+.2f}%)",
            parse_mode="HTML",
            reply_markup=menu_kb,
        )
    except ValueError as e:
        await message.answer(f"❌ {e}", reply_markup=menu_kb)


@dp.message(Command(commands=["portfolio"]))
async def portfolio_cmd(message: Message):
    uid = message.from_user.id
    await db.upsert_user(uid, message.from_user.username)
    p = await game.get_portfolio(uid)

    parts = ["💰 <b>Портфель</b>", ""]
    parts.append(f"▪ Стоимость: ${p['total_value']:,.2f}")
    parts.append(f"▪ Кеш: ${p['balance']:,.2f}")
    sign = "+" if p["total_pnl"] >= 0 else ""
    parts.append(f"▪ P&amp;L: {sign}${p['total_pnl']:,.2f}")
    parts.append(f"▪ Сделок: {p['total_trades']} | Win: {p['win_rate']}%")

    if p["positions"]:
        parts.append("")
        parts.append("── Открытые позиции ──")
        for pos in p["positions"]:
            pnl_sign = "+" if pos["pnl"] >= 0 else ""
            parts.append(f"▸ {pos['side']} {pos['quantity']:.6f} BTC @ ${pos['entry_price']:,.2f}")
            parts.append(f"  P&amp;L: {pnl_sign}${pos['pnl']:,.2f} ({pos['pnl_pct']:+.2f}%)")
    else:
        parts.append("")
        parts.append("💡 Нет открытых позиций. /buy чтобы начать.")

    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=menu_kb)


@dp.message(Command(commands=["leaderboard"]))
async def leaderboard_cmd(message: Message):
    lb = await game.get_leaderboard()
    if not lb:
        await message.answer("🏆 Пока никто не торговал. Стань первым: /buy", reply_markup=menu_kb)
        return

    parts = ["🏆 <b>Топ трейдеров</b>", ""]
    for r in lb[:10]:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(r["rank"], f"#{r['rank']}")
        sign = "+" if r["total_pnl"] >= 0 else ""
        parts.append(f"{medal} {r['username'][:20]}: {sign}${r['total_pnl']:,.2f} ({r['total_trades']} сделок)")

    await message.answer("\n".join(parts), parse_mode="HTML", reply_markup=menu_kb)
