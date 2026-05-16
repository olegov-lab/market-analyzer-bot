import json
import random
from datetime import datetime, timezone
from typing import Optional

from btcbot.db import Database
from loguru import logger


class GameEngine:
    MIN_TRADE_USDT = 10.0
    STARTING_BALANCE = 10000.0
    FEE_PCT = 0.001  # 0.1% total (entry + exit)

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_portfolio(self, user_id: int) -> dict:
        """Return full portfolio: balance, positions with unrealized P&L, recent trades."""
        user = await self.db.get_or_create_game_user(user_id)
        price = await self.db.get_latest_price("BTCUSD") or 0
        positions = await self.db.get_positions(user_id)
        trades = await self.db.get_trades(user_id, limit=5)
        win_rate = (user["winning_trades"] / user["total_trades"] * 100) if user["total_trades"] > 0 else 0

        positions_data = []
        unrealized_total = 0.0
        for p in positions:
            if p["side"] == "LONG":
                pnl = (price - p["entry_price"]) * p["quantity"]
            else:
                pnl = (p["entry_price"] - price) * p["quantity"]
            pnl_pct = (pnl / p["notional"]) * 100 if p["notional"] else 0
            unrealized_total += pnl
            positions_data.append({
                "id": p["id"],
                "side": p["side"],
                "entry_price": round(p["entry_price"], 2),
                "quantity": round(p["quantity"], 6),
                "notional": round(p["notional"], 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "opened_at": p["opened_at"].isoformat() if p["opened_at"] else None,
            })

        total_value = user["balance"] + sum(p["notional"] for p in positions) + unrealized_total

        return {
            "balance": round(user["balance"], 2),
            "total_pnl": round(user["total_pnl"], 2),
            "total_value": round(total_value, 2),
            "unrealized_pnl": round(unrealized_total, 2),
            "total_trades": user["total_trades"],
            "winning_trades": user["winning_trades"],
            "win_rate": round(win_rate, 1),
            "btc_price": round(price, 2),
            "positions": positions_data,
            "recent_trades": [
                {
                    "id": t["id"],
                    "side": t["side"],
                    "entry_price": round(t["entry_price"], 2),
                    "exit_price": round(t["exit_price"], 2),
                    "quantity": round(t["quantity"], 6),
                    "pnl": round(t["pnl"], 2),
                    "pnl_pct": round(t["pnl_pct"], 2),
                    "closed_at": t["closed_at"].isoformat() if t["closed_at"] else None,
                }
                for t in trades
            ],
        }

    async def buy(self, user_id: int, usdt_amount: float) -> dict:
        """Open a LONG position with the given USDT amount."""
        if usdt_amount < self.MIN_TRADE_USDT:
            raise ValueError(f"Минимальная сумма сделки: ${self.MIN_TRADE_USDT}")

        user = await self.db.get_or_create_game_user(user_id)
        if usdt_amount > user["balance"]:
            raise ValueError(f"Недостаточно средств. Доступно: ${user['balance']:,.2f}")

        positions = await self.db.get_positions(user_id)
        if positions:
            raise ValueError("У вас уже есть открытая позиция. Закройте её перед открытием новой.")

        price = await self.db.get_latest_price("BTCUSD")
        if not price:
            raise ValueError("Цена BTC временно недоступна. Попробуйте позже.")

        fee = usdt_amount * self.FEE_PCT
        notional = usdt_amount - fee
        quantity = notional / price

        position = await self.db.open_position(user_id, "LONG", quantity, price, usdt_amount)
        logger.info(f"Game: user {user_id} opened LONG {quantity:.6f} BTC @ ${price:,.2f}")

        return {
            "position_id": position["id"],
            "side": "LONG",
            "quantity": round(quantity, 6),
            "entry_price": round(price, 2),
            "notional": round(usdt_amount, 2),
            "fee": round(fee, 2),
        }

    async def sell(self, user_id: int) -> dict:
        """Close the open LONG position."""
        positions = await self.db.get_positions(user_id)
        if not positions:
            raise ValueError("Нет открытой позиции для продажи.")

        price = await self.db.get_latest_price("BTCUSD")
        if not price:
            raise ValueError("Цена BTC временно недоступна. Попробуйте позже.")

        pos = positions[0]
        trade = await self.db.close_position(user_id, pos["id"], price, self.FEE_PCT)
        if not trade:
            raise ValueError("Не удалось закрыть позицию.")

        logger.info(f"Game: user {user_id} closed position, P&L=${trade['pnl']:.2f}")

        return {
            "trade_id": trade["id"],
            "side": pos["side"],
            "entry_price": round(pos["entry_price"], 2),
            "exit_price": round(price, 2),
            "quantity": round(pos["quantity"], 6),
            "pnl": round(trade["pnl"], 2),
            "pnl_pct": round(trade["pnl_pct"], 2),
            "is_win": trade["pnl"] > 0,
        }

    async def get_history(self, user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
        trades = await self.db.get_trades(user_id, limit, offset)
        return [
            {
                "id": t["id"],
                "side": t["side"],
                "entry_price": round(t["entry_price"], 2),
                "exit_price": round(t["exit_price"], 2),
                "quantity": round(t["quantity"], 6),
                "pnl": round(t["pnl"], 2),
                "pnl_pct": round(t["pnl_pct"], 2),
                "closed_at": t["closed_at"].isoformat() if t["closed_at"] else None,
            }
            for t in trades
        ]

    async def get_leaderboard(self) -> list[dict]:
        rows = await self.db.get_leaderboard()
        return [
            {
                "rank": r["rank"],
                "user_id": r["user_id"],
                "username": r["username"] or f"User {r['user_id']}",
                "total_pnl": round(r["total_pnl"], 2),
                "total_trades": r["total_trades"],
                "win_rate": round(r["win_rate"] * 100, 1),
            }
            for r in rows
        ]

    # ─── Gamification ───────────────────────────────────────────────

    LEAGUES = {"platinum": 10000, "gold": 2000, "silver": 500, "bronze": float("-inf")}
    LEAGUE_NAMES = {"platinum": "Платина", "gold": "Золото", "silver": "Серебро", "bronze": "Бронза"}
    LEAGUE_ORDER = ["bronze", "silver", "gold", "platinum"]
    LEAGUE_COLORS = {"platinum": "#e5e4e2", "gold": "#ffd700", "silver": "#c0c0c0", "bronze": "#cd7f32"}

    @staticmethod
    def compute_league(total_pnl: float) -> dict:
        league = "bronze"
        for name in ["platinum", "gold", "silver"]:
            if total_pnl >= GameEngine.LEAGUES[name]:
                league = name
                break
        idx = GameEngine.LEAGUE_ORDER.index(league)
        next_league = GameEngine.LEAGUE_ORDER[idx + 1] if idx < 3 else None
        progress_pct = 100
        next_threshold = 0
        if next_league:
            threshold = GameEngine.LEAGUES[next_league]
            prev_threshold = GameEngine.LEAGUES[league] if league != "bronze" else 0
            progress_pct = min(100, max(0, (total_pnl - prev_threshold) / (threshold - prev_threshold) * 100))
            next_threshold = threshold
        return {
            "league": league,
            "league_name": GameEngine.LEAGUE_NAMES[league],
            "league_color": GameEngine.LEAGUE_COLORS[league],
            "next_league": next_league,
            "next_league_name": GameEngine.LEAGUE_NAMES.get(next_league),
            "progress_pct": round(progress_pct, 1),
            "next_threshold": next_threshold,
            "total_pnl": round(total_pnl, 2),
        }

    async def get_tournament_state(self, user_id: int) -> dict:
        tournament = await self.db.get_active_tournament()
        result = {"active": False}
        if not tournament:
            upcoming = await self.db.get_tournaments()
            if upcoming:
                t = upcoming[0]
                result["upcoming"] = {"id": t["id"], "name": t["name"], "starts_at": t["starts_at"].isoformat(),
                                       "prize_pool_stars": t["prize_pool_stars"]}
            return result

        entry = await self.db.get_tournament_entry(tournament["id"], user_id)
        entries = await self.db.get_tournament_entries(tournament["id"])
        leaderboard = []
        user_rank = None
        user_ids = [e["user_id"] for e in entries]
        gu_map = {}
        for uid in user_ids:
            gu = await self.db.get_game_user(uid)
            if gu:
                gu_map[uid] = gu
        for i, e in enumerate(entries):
            gu = gu_map.get(e["user_id"])
            pnl_delta = (gu["total_pnl"] - e["start_pnl"]) if gu else 0
            entry_data = {"rank": i + 1, "user_id": e["user_id"], "username": e["username"] or f"User {e['user_id']}",
                          "pnl_delta": round(pnl_delta, 2)}
            leaderboard.append(entry_data)
            if e["user_id"] == user_id:
                user_rank = i + 1

        return {
            "active": True,
            "id": tournament["id"],
            "name": tournament["name"],
            "ends_at": tournament["ends_at"].isoformat(),
            "prize_pool_stars": tournament["prize_pool_stars"],
            "participants": len(entries),
            "joined": entry is not None,
            "user_rank": user_rank,
            "leaderboard": leaderboard[:20],
        }

    async def join_tournament(self, tournament_id: int, user_id: int) -> dict:
        user = await self.db.get_or_create_game_user(user_id)
        entry = await self.db.join_tournament(tournament_id, user_id, user["total_pnl"] or 0)
        return {"joined": entry is not None, "tournament_id": tournament_id, "start_pnl": round(user["total_pnl"] or 0, 2)}

    async def get_referral_info(self, user_id: int) -> dict:
        stats = await self.db.get_referral_stats(user_id)
        return {"count": stats["count"], "total_bonus": stats["total_bonus"],
                "referrals": stats["referrals"], "ref_link": f"https://t.me/Market04ekBot?start=ref_{user_id}"}

    async def add_referral(self, referrer_id: int, referred_id: int) -> dict:
        ok = await self.db.create_referral(referrer_id, referred_id)
        if ok:
            refs = await self.db.get_referral_stats(referrer_id)
            if refs["referrals"]:
                await self.db.credit_referral_bonus(refs["referrals"][0]["id"])
        return {"success": ok}

    async def get_pnl_card_data(self, user_id: int) -> dict:
        user = await self.db.get_or_create_game_user(user_id)
        trades = await self.db.get_trades(user_id, limit=100)
        league = self.compute_league(user["total_pnl"] or 0)
        win_rate = 0
        if user["total_trades"] > 0:
            win_rate = round(user["winning_trades"] / user["total_trades"] * 100, 1)
        recent = []
        for t in trades[:5]:
            recent.append({"pnl": round(t["pnl"], 2), "pnl_pct": round(t["pnl_pct"], 2),
                           "side": t["side"], "closed_at": t["closed_at"].isoformat() if t["closed_at"] else None})
        return {
            "league": league,
            "total_pnl": round(user["total_pnl"] or 0, 2),
            "balance": round(user["balance"] or 0, 2),
            "total_trades": user["total_trades"],
            "win_rate": win_rate,
            "stars": user["stars"] or 0,
            "recent_trades": recent,
        }

    # ─── Price Guess ──────────────────────────────────────────────────

    async def submit_guess(self, user_id: int, guess_price: float) -> dict:
        if guess_price <= 0:
            raise ValueError("Цена должна быть положительной")
        current_price = await self.db.get_latest_price("BTCUSD")
        if not current_price:
            raise ValueError("Цена BTC временно недоступна")
        result = await self.db.submit_price_guess(user_id, guess_price)
        return {"guess_price": result["guess_price"], "guess_date": result["guess_date"], "btc_price": current_price}

    async def get_guess_state(self, user_id: int) -> dict:
        today = await self.db.get_user_guess_today(user_id)
        current_price = await self.db.get_latest_price("BTCUSD")
        history = await self.db.get_guess_history(user_id, 10)
        user = await self.db.get_or_create_game_user(user_id)
        return {
            "today_guess": {"guess_price": today["guess_price"]} if today else None,
            "btc_price": current_price,
            "stars": user.get("stars", 0),
            "history": [
                {"date": str(h["guess_date"]), "guess_price": h["guess_price"],
                 "btc_price": h["btc_price_at_resolution"], "deviation_pct": h["deviation_pct"],
                 "won": h["won"], "stars_won": h["stars_won"]}
                for h in history
            ],
        }

    # ─── Achievements ─────────────────────────────────────────────────

    async def check_and_unlock(self, user_id: int, slug: str) -> Optional[dict]:
        return await self.db.unlock_achievement(user_id, slug)

    async def get_achievements_state(self, user_id: int) -> dict:
        achievements = await self.db.get_user_achievements(user_id)
        unlocked = sum(1 for a in achievements if a["unlocked_at"])
        return {
            "total": len(achievements),
            "unlocked": unlocked,
            "list": [
                {"slug": a["slug"], "name": a["name"], "icon": a["icon"],
                 "category": a["category"], "description": a["description"],
                 "unlocked": a["unlocked_at"] is not None,
                 "unlocked_at": a["unlocked_at"].isoformat() if a["unlocked_at"] else None}
                for a in achievements
            ],
        }

    async def check_trade_achievements(self, user_id: int) -> list[dict]:
        user = await self.db.get_or_create_game_user(user_id)
        new = []
        total = user["total_trades"] or 0
        pnl = user["total_pnl"] or 0
        win_rate = (user["winning_trades"] / total * 100) if total > 0 else 0

        checks = [
            ("first_trade", total >= 1),
            ("ten_trades", total >= 10),
            ("fifty_trades", total >= 50),
            ("profit_100", pnl >= 100),
            ("profit_1000", pnl >= 1000),
            ("profit_10000", pnl >= 10000),
        ]
        for slug, condition in checks:
            if condition:
                r = await self.check_and_unlock(user_id, slug)
                if r:
                    new.append(r)

        # Win streak check
        if total >= 3 and win_rate >= 80:
            r = await self.check_and_unlock(user_id, "win_streak_3")
            if r:
                new.append(r)

        # League check
        league_info = self.compute_league(pnl)
        if league_info["league"] == "platinum":
            r = await self.check_and_unlock(user_id, "platinum_league")
            if r:
                new.append(r)

        return new

    async def check_guess_achievements(self, user_id: int, won: bool) -> list[dict]:
        new = []
        if won:
            r = await self.check_and_unlock(user_id, "guess_winner")
            if r:
                new.append(r)
        # Check streak
        history = await self.db.get_guess_history(user_id, 5)
        if len(history) >= 3:
            r = await self.check_and_unlock(user_id, "guess_3_streak")
            if r:
                new.append(r)
        return new

    async def check_mining_achievements(self, user_id: int, total_sats: int) -> list[dict]:
        new = []
        checks = [
            ("mining_1000", total_sats >= 1000),
            ("mining_10000", total_sats >= 10000),
        ]
        for slug, condition in checks:
            if condition:
                r = await self.check_and_unlock(user_id, slug)
                if r:
                    new.append(r)
        return new

    async def check_referral_achievements(self, user_id: int) -> list[dict]:
        stats = await self.db.get_referral_stats(user_id)
        new = []
        checks = [
            ("referral_3", stats["count"] >= 3),
            ("referral_10", stats["count"] >= 10),
        ]
        for slug, condition in checks:
            if condition:
                r = await self.check_and_unlock(user_id, slug)
                if r:
                    new.append(r)
        return new

    # ─── Mining (Tap-to-Earn) ────────────────────────────────────────

    async def mine_click(self, user_id: int, redis) -> dict:
        key = f"mining:{user_id}"
        now = datetime.now(timezone.utc)
        data = await redis.get(key)
        state = json.loads(data) if data else {"earned": 0, "last_click": None, "streak": 0}

        last = state.get("last_click")
        streak = state.get("streak", 0)

        if last:
            last_dt = datetime.fromisoformat(last)
            hours_since = (now - last_dt).total_seconds() / 3600
            if hours_since < 1:
                raise ValueError("Копать можно раз в час! Возвращайтесь через {:.0f} мин.".format(60 - (now - last_dt).total_seconds() / 60))
            if hours_since > 24:
                streak = 0
            else:
                streak += 1
        else:
            streak = 1

        base_sats = random.randint(3, 8)
        streak_mult = min(2.0, 1 + streak * 0.05)
        refs = await self.db.get_referral_stats(user_id)
        ref_mult = 1 + min(1.0, refs["count"] * 0.1)
        earned = round(base_sats * streak_mult * ref_mult, 0)

        state["earned"] += earned
        state["last_click"] = now.isoformat()
        state["streak"] = streak

        await redis.set(key, json.dumps(state, ensure_ascii=False))

        # Convert sats to Stars (1000 sats = 1 star)
        sats_to_stars = int(state["earned"] // 1000)
        total_stars = int(sats_to_stars)

        return {
            "earned": int(earned),
            "total_sats": int(state["earned"]),
            "streak": streak,
            "streak_mult": round(streak_mult, 2),
            "ref_mult": round(ref_mult, 2),
            "stars": total_stars,
        }

    async def roulette_spin(self, user_id: int, bet: int, redis) -> dict:
        if bet < 1 or bet > 10:
            raise ValueError("Ставка от 1 до 10 ⭐")
        if not isinstance(bet, int):
            raise ValueError("Ставка должна быть целым числом")

        # Cooldown: 1 spin per 3 seconds
        cooldown_key = f"roulette:cd:{user_id}"
        if await redis.get(cooldown_key):
            raise ValueError("Крутить можно раз в 3 секунды")

        # Check balance
        user = await self.db.get_or_create_game_user(user_id)
        if (user.get("stars") or 0) < bet:
            raise ValueError(f"Недостаточно ⭐. Баланс: {user.get('stars', 0)}")

        # Deduct bet
        async with self.db.pool.acquire() as conn:
            await conn.execute("UPDATE game_users SET stars = stars - $1 WHERE user_id = $2", bet, user_id)

        # Roll the dice
        roll = random.random()
        outcomes = [
            (0.40, 0, "😢"),   # 40% lose
            (0.70, 1.5, "🟡"),  # 30% x1.5
            (0.90, 2.0, "🟢"),  # 20% x2
            (0.99, 3.0, "🔵"),  # 9%  x3
            (1.00, 5.0, "💎"),  # 1%  x5
        ]
        multiplier = 0
        emoji = ""
        for cum_prob, mult, emj in outcomes:
            if roll <= cum_prob:
                multiplier = mult
                emoji = emj
                break

        win_amount = int(bet * multiplier)
        net = win_amount - bet
        won = net > 0

        if win_amount > 0:
            await self.db.add_stars(user_id, win_amount)

        # Record spin in Redis (last 20)
        history_key = f"roulette:history:{user_id}"
        spin = {
            "bet": bet, "multiplier": multiplier, "win": win_amount,
            "net": net, "ts": datetime.now(timezone.utc).isoformat()
        }
        raw = await redis.get(history_key)
        history = json.loads(raw) if raw else []
        history.append(spin)
        if len(history) > 20:
            history = history[-20:]
        await redis.setex(history_key, 86400, json.dumps(history, ensure_ascii=False))
        await redis.setex(cooldown_key, 3, "1")

        return {
            "bet": bet, "multiplier": multiplier, "win": win_amount,
            "net": net, "won": won, "emoji": emoji,
        }

    async def get_mining_state(self, user_id: int, redis) -> dict:
        key = f"mining:{user_id}"
        data = await redis.get(key)
        state = json.loads(data) if data else {"earned": 0, "last_click": None, "streak": 0}

        now = datetime.now(timezone.utc)
        can_mine = True
        cooldown_min = 0
        if state.get("last_click"):
            last_dt = datetime.fromisoformat(state["last_click"])
            secs_since = (now - last_dt).total_seconds()
            if secs_since < 3600:
                can_mine = False
                cooldown_min = int(60 - secs_since / 60)

        refs = await self.db.get_referral_stats(user_id)
        ref_mult = 1 + min(1.0, refs["count"] * 0.1)
        streak_mult = min(2.0, 1 + state.get("streak", 0) * 0.05)

        sats_to_stars = int(state["earned"] // 1000)
        return {
            "total_sats": int(state["earned"]),
            "streak": state.get("streak", 0),
            "can_mine": can_mine,
            "cooldown_min": cooldown_min,
            "ref_mult": round(ref_mult, 2),
            "streak_mult": round(streak_mult, 2),
            "stars": int(sats_to_stars),
            "referrals": refs["count"],
        }
