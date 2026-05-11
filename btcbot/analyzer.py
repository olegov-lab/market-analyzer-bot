import asyncio
import math
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
import pandas_ta as ta
from loguru import logger
from pydantic import BaseModel

from btcbot.db import Database
from btcbot.models import IndicatorSet, LiquidityZone, OnChainScore, Prediction, VolatilityData

MODEL_PATH = "models/lgb_4h.txt"
TRAIN_DAYS = 90
INFERENCE_DAYS = 50

LGB_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "num_threads": 2,
}

ONCHAIN_WEIGHTS = {
    "mvrv_z": 0.30,
    "sopr": 0.20,
    "nupl": 0.20,
    "puell": 0.15,
    "rhodl": 0.15,
}

ONCHAIN_RULES = {
    "mvrv_z": [(0.5, 1), (3.0, 0), (7.0, -1), (float("inf"), -2)],
    "sopr": [(0.95, 1), (1.05, 0), (1.20, -1), (float("inf"), -2)],
    "nupl": [(0.25, 1), (0.50, 0), (0.75, -1), (float("inf"), -2)],
    "puell": [(0.5, 1), (2.0, 0), (4.0, -1), (float("inf"), -2)],
    "rhodl": [(0.5, 1), (2.0, 0), (5.0, -1), (float("inf"), -2)],
}


def _to_val(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        val = float(v)
        return None if math.isnan(val) else val
    except (ValueError, TypeError):
        return None


def _apply_rules(value: Optional[float], rules: list) -> int:
    if value is None:
        return 0
    for threshold, score in rules:
        if value < threshold:
            return score
    return -2


class Analyzer:
    _lgb_model: Optional[lgb.Booster] = None
    _lgb_lock = threading.Lock()
    _is_training = False

    def __init__(self, db: Database, redis_client: Any) -> None:
        self.db = db
        self.redis = redis_client

    async def warmup_cache(self):
        await asyncio.sleep(1)
        try:
            await self.compute_indicators()
            await self.predict()
            logger.info("Cache warmed up")
        except Exception as e:
            logger.warning("Warmup incomplete: {}", e)

    async def compute_indicators(self, symbol: str = "BTCUSD") -> Optional[Any]:
        cache_key = f"indicators:{symbol}"
        cached = await self.redis.get(cache_key)
        if cached is not None:
            return IndicatorSet.model_validate_json(cached)
        since = datetime.now(timezone.utc) - timedelta(hours=48)
        rows = await self.db.get_1m_candles_since(symbol, since)
        if len(rows) < 14:
            logger.warning("Not enough data for indicators: {} rows", len(rows))
            return None

        df = pd.DataFrame(rows, columns=["time", "price", "volume"])
        df.set_index("time", inplace=True)
        df = df.dropna()
        candles = len(df)

        closes = df["price"].astype(float)
        volumes = df["volume"].astype(float)

        rsi_series = ta.rsi(closes, length=14) if candles >= 14 else None
        macd_df = ta.macd(closes, fast=12, slow=26, signal=9) if candles >= 26 else None
        bb_df = ta.bbands(closes, length=20, std=2) if candles >= 20 else None
        obv_series = ta.obv(closes, volumes)

        ma_50 = closes.rolling(50).mean()
        ma_100 = closes.rolling(100).mean()
        ma_200 = closes.rolling(200).mean()

        now = datetime.now(timezone.utc)

        result = IndicatorSet(
            time=now,
            symbol=symbol,
            rsi=_to_val(rsi_series.iloc[-1] if rsi_series is not None and not rsi_series.empty else None),
            macd=_to_val(macd_df.iloc[-1]["MACD_12_26_9"] if macd_df is not None and not macd_df.empty else None),
            macd_signal=_to_val(macd_df.iloc[-1]["MACDs_12_26_9"] if macd_df is not None and not macd_df.empty else None),
            macd_hist=_to_val(macd_df.iloc[-1]["MACDh_12_26_9"] if macd_df is not None and not macd_df.empty else None),
            ma_50=_to_val(ma_50.iloc[-1] if not ma_50.empty else None),
            ma_100=_to_val(ma_100.iloc[-1] if not ma_100.empty else None),
            ma_200=_to_val(ma_200.iloc[-1] if not ma_200.empty else None),
            bb_upper=_to_val(bb_df.iloc[-1][[c for c in bb_df.columns if c.startswith("BBU_")][0]] if bb_df is not None and not bb_df.empty else None),
            bb_middle=_to_val(bb_df.iloc[-1][[c for c in bb_df.columns if c.startswith("BBM_")][0]] if bb_df is not None and not bb_df.empty else None),
            bb_lower=_to_val(bb_df.iloc[-1][[c for c in bb_df.columns if c.startswith("BBL_")][0]] if bb_df is not None and not bb_df.empty else None),
            obv=_to_val(obv_series.iloc[-1] if obv_series is not None and not obv_series.empty else None),
        )
        try:
            await self.redis.setex(cache_key, 30, result.model_dump_json())
        except Exception:
            pass
        return result

    async def compute_volatility(self, symbol: str = "BTCUSD") -> Optional[VolatilityData]:
        cache_key = f"volatility:{symbol}"
        cached = await self.redis.get(cache_key)
        if cached:
            return VolatilityData.model_validate_json(cached)
        since = datetime.now(timezone.utc) - timedelta(days=30)
        rows = await self.db.get_hourly_candles_since(symbol, since)
        if not rows or len(rows) < 5:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        df = df.rename(columns={"bucket": "time"})
        df = df.set_index("time").sort_index()
        n = len(df)
        bb_len = min(20, max(3, n - 2))
        atr_len = min(14, max(2, n - 2))
        bb = ta.bbands(df["close"], length=bb_len, std=2)
        atr_series = ta.atr(df["high"], df["low"], df["close"], length=atr_len)
        if bb is None or bb.empty or atr_series is None or atr_series.empty:
            return None
        bb_cols = [c for c in bb.columns if c.startswith("BBU_")]
        if not bb_cols:
            return None
        bb_u = bb[bb_cols[0]]
        bb_l = bb[[c for c in bb.columns if c.startswith("BBL_")][0]]
        bb_m = bb[[c for c in bb.columns if c.startswith("BBM_")][0]]
        bb_width = (bb_u - bb_l) / bb_m * 100
        atr_pct = atr_series / df["close"] * 100
        valid_mask = bb_width.notna() & atr_pct.notna()
        valid = bb_width[valid_mask]
        if valid.empty or len(valid) < 2:
            return None
        current_bb = float(bb_width.iloc[-1])
        current_atr = float(atr_pct.iloc[-1])
        bb_min, bb_max = float(bb_width.min()), float(bb_width.max())
        atr_min, atr_max = float(atr_pct.min()), float(atr_pct.max())
        bb_norm = (current_bb - bb_min) / (bb_max - bb_min) if bb_max > bb_min else 0.5
        atr_norm = (current_atr - atr_min) / (atr_max - atr_min) if atr_max > atr_min else 0.5
        pct = sum(bb_width <= current_bb) / len(bb_width) * 100
        score = 0.3 * bb_norm + 0.3 * atr_norm + 0.4 * (pct / 100)
        score = max(0.0, min(1.0, score))
        if score < 0.25:
            cls = "low"
        elif score < 0.5:
            cls = "medium"
        elif score < 0.75:
            cls = "high"
        else:
            cls = "extreme"
        bb_window = bb_width.iloc[-48:] if len(bb_width) >= 48 else bb_width
        atr_window = atr_pct.iloc[-48:] if len(atr_pct) >= 48 else atr_pct
        bb_mm, bb_mx = float(bb_window.min()), float(bb_window.max())
        atr_mm, atr_mx = float(atr_window.min()), float(atr_window.max())
        history = []
        for i in range(len(bb_window)):
            bbn = (float(bb_window.iloc[i]) - bb_mm) / (bb_mx - bb_mm) if bb_mx > bb_mm else 0.5
            atrn = (float(atr_window.iloc[i]) - atr_mm) / (atr_mx - atr_mm) if atr_mx > atr_mm else 0.5
            bp = sum(bb_window.iloc[:i+1] <= bb_window.iloc[i]) / (i + 1) * 100 if i > 0 else 50
            history.append(min(1.0, 0.3 * bbn + 0.3 * atrn + 0.4 * (bp / 100)))
        result = VolatilityData(
            current=round(score, 4),
            classification=cls,
            bb_width_pct=round(float(current_bb), 2),
            atr_pct=round(float(current_atr), 2),
            percentile=round(float(pct), 1),
            history=[round(h, 4) for h in history[-24:]],
        )
        try:
            await self.redis.setex(cache_key, 60, result.model_dump_json())
        except Exception:
            pass
        return result

    async def compute_consensus(self) -> dict:
        """13 indicators × 4 groups. Each votes +1/-1/0. Returns bullish_pct 0-100."""
        cache_key = "consensus"
        cached = await self.redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

        indicators = await self.compute_indicators()
        if not indicators:
            return {"bullish_pct": 50, "signal": "neutral", "available": 0, "low_confidence": True}

        fng = None
        try:
            from btcbot.fear_greed import FearGreedIndex
            fgi = FearGreedIndex(self.redis)
            fng = await fgi.fetch()
        except Exception:
            pass

        price = await self.db.get_latest_price("BTCUSD")

        def vote(name, value, ctx):
            if value is None:
                return None
            rules = {
                "ma50": lambda: 1 if price and price > value else -1,
                "ma200": lambda: 1 if price and price > value else -1,
                "macd_signal": lambda: 1 if indicators.macd and indicators.macd > value else (-1 if indicators.macd and indicators.macd < value else 0),
                "rsi": lambda: 1 if value < 30 else (-1 if value > 70 else 0),
                "bb_position": lambda: 1 if value < 20 else (-1 if value > 80 else 0),
                "funding_rate": lambda: 1 if value < -0.005 else (-1 if value > 0.01 else 0),
                "fear_greed": lambda: 1 if value < 25 else (-1 if value > 75 else 0),
            }
            fn = rules.get(name)
            return fn() if fn else 0

        groups = {
            "trend": {"weight": 0.30, "members": {"ma50": (indicators.ma_50, 0.35), "ma200": (indicators.ma_200, 0.35), "macd_signal": (indicators.macd_signal, 0.30)}},
            "momentum": {"weight": 0.25, "members": {"rsi": (indicators.rsi, 0.40), "bb_position": (self._bb_position(indicators, price), 0.30)}},
            "sentiment": {"weight": 0.20, "members": {"fear_greed": (fng["value"] if fng else None, 0.50), "funding_rate": (indicators.funding_rate, 0.50)}},
        }

        group_scores = {}
        total_available = 0
        for gname, gconf in groups.items():
            g_score = 0.0
            g_available = 0
            g_weight_sum = 0.0
            for ind_name, (val, w) in gconf["members"].items():
                v = vote(ind_name, val, {})
                if v is not None:
                    g_score += v * w
                    g_weight_sum += w
                    g_available += 1
                    total_available += 1
            group_scores[gname] = g_score / g_weight_sum if g_weight_sum > 0 else 0.0

        final = sum(group_scores[g] * groups[g]["weight"] for g in groups)
        bullish_pct = round((final + 1) / 2 * 100)
        bullish_pct = max(5, min(95, bullish_pct))

        if bullish_pct >= 70:
            signal = "strong_bullish"
        elif bullish_pct >= 55:
            signal = "bullish"
        elif bullish_pct >= 45:
            signal = "neutral"
        elif bullish_pct >= 30:
            signal = "bearish"
        else:
            signal = "strong_bearish"

        result = {
            "bullish_pct": bullish_pct,
            "bearish_pct": 100 - bullish_pct,
            "signal": signal,
            "available": total_available,
            "low_confidence": total_available < 4,
        }
        import json
        await self.redis.setex(cache_key, 60, json.dumps(result))
        return result

    def _bb_position(self, indicators, price):
        if not indicators or not price or not indicators.bb_lower or not indicators.bb_upper:
            return None
        denom = indicators.bb_upper - indicators.bb_lower
        if denom == 0:
            return None
        return max(0, min(100, (price - indicators.bb_lower) / denom * 100))

    async def predict(self, symbol: str = "BTCUSD") -> Optional[Prediction]:
        cache_key = f"prediction:{symbol}"
        cached = await self.redis.get(cache_key)
        if cached is not None:
            return Prediction.model_validate_json(cached)

        price = await self.db.get_latest_price(symbol)
        if not price:
            return None

        result_4h, result_1w, result_long = await asyncio.gather(
            self._predict_4h(symbol),
            self._predict_1w(symbol),
            self._predict_long(symbol),
        )

        if not result_4h:
            indicators = await self.compute_indicators(symbol)
            if not indicators or indicators.rsi is None:
                return None
            direction = "BUY" if indicators.rsi < 30 else "SELL" if indicators.rsi > 70 else "HOLD"
            confidence = round(abs(50 - indicators.rsi) / 50, 2)
            atr_val = price * 0.01
            try:
                rows_atr = await self.db.get_prices_since(symbol, datetime.now(timezone.utc) - timedelta(days=1))
                if len(rows_atr) >= 15:
                    df_atr = pd.DataFrame(rows_atr, columns=["time", "p", "v"])
                    df_atr = df_atr.resample("1min", on="time").agg({"p": "last"}).dropna()
                    c = df_atr["p"].astype(float)
                    atr_series = ta.atr(c, c, c, length=14)
                    if atr_series is not None and not atr_series.empty:
                        atr_val = float(atr_series.iloc[-1])
            except Exception:
                pass
            spread = atr_val * 2.5
            now = datetime.now(timezone.utc)
            result_4h = {
                "direction": direction,
                "confidence": confidence,
                "price_min": round(price - spread, 2),
                "price_max": round(price + spread, 2),
                "time": now.isoformat(),
                "fallback": True,
                "liquidity_zones": [],
            }

        pred = Prediction(
            time=result_4h["time"],
            horizon="4h",
            price_min=result_4h["price_min"],
            price_max=result_4h["price_max"],
            direction=result_4h["direction"],
            confidence=result_4h["confidence"],
            meta={
                "prediction_4h": result_4h,
                "prediction_1w": result_1w.model_dump() if isinstance(result_1w, BaseModel) else result_1w,
                "prediction_long": result_long,
            },
        )
        await self.db.save_prediction(pred)
        try:
            await self.redis.setex(cache_key, 300, pred.model_dump_json())
        except Exception:
            pass
        return pred

    async def _build_4h_candles(self, symbol: str, since: datetime) -> Optional[pd.DataFrame]:
        rows = await self.db.get_4h_candles_since(symbol, since)
        if len(rows) < 100:
            return None

        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        df.set_index("time", inplace=True)
        return df

    async def _get_onchain_df(self, since: datetime) -> pd.DataFrame:
        rows = await self.db.get_all_onchain_metrics_since(since)
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["time", "metric_name", "value"])
        df["time"] = pd.to_datetime(df["time"])
        df.set_index("time", inplace=True)
        df = df.pivot_table(index="time", columns="metric_name", values="value", aggfunc="mean")
        df = df.resample("4h").ffill().bfill()
        df.columns = [str(c) for c in df.columns]

        for col in ["funding_rate", "long_short_ratio", "open_interest"]:
            if col not in df.columns:
                df[col] = 0.0

        return df

    def _compute_24_features(self, candles: pd.DataFrame, onchain: pd.DataFrame = None) -> pd.DataFrame:
        df = candles.copy()
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        df["return_1h"] = np.log(close / close.shift(1))
        df["return_4h"] = np.log(close / close.shift(4))
        df["volatility_4h"] = df["return_1h"].rolling(6).std()
        df["high_low_ratio_4h"] = (high - low) / close
        df["volume_change_4h"] = volume / volume.shift(4) - 1

        bb_m = close.rolling(20).mean()
        bb_s = close.rolling(20).std()
        bb_u = bb_m + 2 * bb_s
        bb_l = bb_m - 2 * bb_s
        df["close_position_bb"] = (close - bb_l) / (bb_u - bb_l)

        ma50 = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()
        df["distance_ma50"] = (close - ma50) / ma50
        df["distance_ma200"] = (close - ma200) / ma200

        df["rsi_14"] = ta.rsi(close, length=14)
        df["rsi_change"] = df["rsi_14"] - df["rsi_14"].shift(4)

        macd = ta.macd(close, fast=12, slow=26, signal=9)
        if macd is not None and not macd.empty:
            df["macd_hist"] = macd["MACDh_12_26_9"]
        else:
            df["macd_hist"] = 0.0
        df["macd_hist_change"] = df["macd_hist"] - df["macd_hist"].shift(4)

        obv = ta.obv(close, volume)
        df["obv_change"] = (obv - obv.shift(4)) / obv.shift(4).replace(0, np.nan)

        atr = ta.atr(high, low, close, length=14)
        df["atr_14"] = atr / close

        adx = ta.adx(high, low, close, length=14)
        df["adx_14"] = adx["ADX_14"] if adx is not None and not adx.empty else 0.0

        df["williams_r"] = ta.willr(high, low, close, length=14)

        df.index = pd.DatetimeIndex(df.index)
        df["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
        df["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
        df["dayofweek_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 7)
        df["dayofweek_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 7)

        if onchain is not None and not onchain.empty:
            oc_cols = [c for c in ["funding_rate", "long_short_ratio", "open_interest"] if c in onchain.columns]
            if oc_cols:
                df = df.join(onchain[oc_cols], how="left", rsuffix="_oc")
                for col in oc_cols:
                    oc_suffixed = f"{col}_oc"
                    if oc_suffixed in df.columns:
                        default_val = 1.0 if col == "long_short_ratio" else 0.0
                        df[col] = df[oc_suffixed].fillna(default_val)
                        df.drop(columns=[oc_suffixed], inplace=True)
        else:
            df["funding_rate"] = 0.0
            df["long_short_ratio"] = 1.0
            df["open_interest"] = 0.0

        df["funding_rate_change"] = df["funding_rate"] - df["funding_rate"].shift(4)
        oi = df["open_interest"]
        oi_pct = oi / oi.shift(4) - 1
        has_oi_data = (oi != 0).any()
        df["oi_change"] = oi_pct.where(has_oi_data, df["funding_rate"] * df["volume_change_4h"].fillna(0))

        feature_cols = [
            "return_1h", "return_4h", "volatility_4h", "high_low_ratio_4h",
            "volume_change_4h", "close_position_bb", "distance_ma50", "distance_ma200",
            "rsi_14", "rsi_change", "macd_hist", "macd_hist_change",
            "obv_change", "atr_14", "adx_14", "williams_r",
            "hour_sin", "hour_cos", "dayofweek_sin", "dayofweek_cos",
            "funding_rate", "funding_rate_change", "long_short_ratio", "oi_change",
        ]

        return df[feature_cols]

    def _liquidity_zones(self, candles: pd.DataFrame) -> list[dict]:
        if len(candles) < 24:
            return []
        recent = candles.tail(24)
        local_high = float(recent["high"].max())
        local_low = float(recent["low"].min())

        current_price = float(candles["close"].iloc[-1])

        zones = []

        long_zone_price = round(local_low * 0.98, 2)
        if current_price > long_zone_price:
            zones.append({
                "type": "long",
                "price": long_zone_price,
                "description": "накопление стопов",
            })

        short_zone_price = round(local_high * 1.02, 2)
        if current_price < short_zone_price:
            zones.append({
                "type": "short",
                "price": short_zone_price,
                "description": "ликвидации шортистов",
            })

        return zones

    async def _load_or_train_model(self, symbol: str, candles: pd.DataFrame) -> Optional[lgb.Booster]:
        with Analyzer._lgb_lock:
            if Analyzer._lgb_model is not None:
                return Analyzer._lgb_model

            if os.path.exists(MODEL_PATH):
                try:
                    Analyzer._lgb_model = lgb.Booster(model_file=MODEL_PATH)
                    logger.info("Loaded LightGBM model from {}", MODEL_PATH)
                    return Analyzer._lgb_model
                except Exception as e:
                    logger.warning("Failed to load model: {}, retraining", e)

            if not Analyzer._is_training:
                Analyzer._is_training = True
                do_train = True
            else:
                do_train = False

        if do_train:
            try:
                logger.info("Training LightGBM model on last {} days of data", TRAIN_DAYS)
                model = await self._train_model(symbol, candles)
                if model:
                    with Analyzer._lgb_lock:
                        Analyzer._lgb_model = model
                return model
            finally:
                with Analyzer._lgb_lock:
                    Analyzer._is_training = False

        for _ in range(120):
            with Analyzer._lgb_lock:
                if Analyzer._lgb_model is not None:
                    return Analyzer._lgb_model
            await asyncio.sleep(0.5)
        return None

    async def _get_model(self, symbol: str, candles: pd.DataFrame) -> Optional[lgb.Booster]:
        with Analyzer._lgb_lock:
            if Analyzer._lgb_model is not None:
                return Analyzer._lgb_model

        if Analyzer._is_training:
            for _ in range(120):
                with Analyzer._lgb_lock:
                    if Analyzer._lgb_model is not None:
                        return Analyzer._lgb_model
                await asyncio.sleep(0.5)

        return await self._load_or_train_model(symbol, candles)

    async def _train_model(self, symbol: str, candles: pd.DataFrame) -> Optional[lgb.Booster]:
        try:
            oc_since = candles.index[0] - timedelta(days=1)
            onchain = await self._get_onchain_df(oc_since)
            features_df = self._compute_24_features(candles, onchain)

            close = candles["close"].astype(float)
            future_ret = np.log(close.shift(-1) / close)
            targets = np.where(
                future_ret > 0.015, 0,
                np.where(future_ret < -0.015, 2, 1)
            )

            valid = features_df.notna().all(axis=1) & (targets != -1)
            X = features_df[valid].values.astype(np.float32)
            y = targets[valid].astype(np.int32)

            if len(X) < 200:
                logger.warning("Not enough training samples: {}", len(X))
                return None

            split = int(len(X) * 0.8)
            X_train, X_val = X[:split], X[split:]
            y_train, y_val = y[:split], y[split:]

            train_data = lgb.Dataset(X_train, label=y_train)
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

            loop = asyncio.get_running_loop()
            model = await loop.run_in_executor(
                None, lambda: lgb.train(
                    LGB_PARAMS, train_data,
                    valid_sets=[val_data],
                    num_boost_round=500,
                    callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)],
                ),
            )

            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            model.save_model(MODEL_PATH)
            logger.info("Trained and saved model to {} (samples: {})", MODEL_PATH, len(X))
            return model

        except Exception as e:
            logger.error("Model training failed: {}", e)
            return None

    async def _predict_4h(self, symbol: str) -> Optional[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=INFERENCE_DAYS)
        candles = await self._build_4h_candles(symbol, since)
        if candles is None or len(candles) < 50:
            logger.warning("Not enough 4h candles for prediction: {}", len(candles) if candles is not None else 0)
            return None

        oc_since = candles.index[0] - timedelta(days=1)
        onchain = await self._get_onchain_df(oc_since)
        features_df = self._compute_24_features(candles, onchain)

        model = await self._get_model(symbol, candles)
        latest_features = features_df.iloc[-1:].fillna(0)

        atr_val = float(candles["close"].astype(float).iloc[-1] * 0.02)
        try:
            atr_series = ta.atr(candles["high"].astype(float), candles["low"].astype(float), candles["close"].astype(float), length=14)
            if atr_series is not None and not atr_series.empty and not np.isnan(atr_series.iloc[-1]):
                atr_val = float(atr_series.iloc[-1])
        except Exception:
            pass

        direction = "HOLD"
        confidence = 0.5
        probs_list = None

        if model is not None:
            try:
                feats = latest_features.values.astype(np.float32)
                loop = asyncio.get_running_loop()
                probs = await loop.run_in_executor(None, model.predict, feats)
                probs_list = probs[0].tolist()
                pred_class = int(np.argmax(probs[0]))
                label_map = {0: "BUY", 1: "HOLD", 2: "SELL"}
                direction = label_map[pred_class]

                p_dir = probs[0][pred_class]
                entropy = -sum(p * math.log(p + 1e-15) for p in probs[0])
                confidence = round(p_dir * (1 - entropy / math.log(3)), 4)

            except Exception as e:
                logger.error("ML prediction failed: {}, falling back to RSI", e)
                model = None

        if model is None:
            close_vals = candles["close"].astype(float).tail(50)
            rsi_val = ta.rsi(close_vals, length=14)
            if rsi_val is not None and not rsi_val.empty:
                rsi_last = float(rsi_val.iloc[-1])
                direction = "BUY" if rsi_last < 30 else "SELL" if rsi_last > 70 else "HOLD"
                confidence = round(abs(50 - rsi_last) / 50, 4)
            else:
                direction = "HOLD"
                confidence = 0.5

        current_price = float(candles["close"].iloc[-1])
        price_min = round(current_price * (1 - atr_val / current_price * 2.5), 2)
        price_max = round(current_price * (1 + atr_val / current_price * 2.5), 2)

        zones = self._liquidity_zones(candles)

        feature_dict = {}
        try:
            feature_dict = latest_features.iloc[-1].fillna(0).to_dict()
        except Exception:
            pass

        return {
            "direction": direction,
            "confidence": confidence,
            "price_min": price_min,
            "price_max": price_max,
            "time": datetime.now(timezone.utc).isoformat(),
            "atr_14": round(atr_val / current_price, 6) if current_price else 0,
            "current_price": current_price,
            "liquidity_zones": zones,
            "features": feature_dict,
            "probabilities": probs_list,
            "fallback": model is None,
        }

    async def _predict_1w(self, symbol: str) -> Optional[OnChainScore]:
        since = datetime.now(timezone.utc) - timedelta(days=14)
        rows = await self.db.get_all_onchain_metrics_since(since)
        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["time", "metric_name", "value"])
        df = df.sort_values("time")
        latest = df.groupby("metric_name").last()["value"].to_dict()

        mvrv_z = _to_val(latest.get("mvrv_z_score"))
        sopr = _to_val(latest.get("sopr_realized"))
        nupl = _to_val(latest.get("nupl"))
        puell = _to_val(latest.get("puell_multiple"))
        rhodl = _to_val(latest.get("rhodl_ratio"))

        scores = {}
        scores["mvrv_z"] = _apply_rules(mvrv_z, ONCHAIN_RULES["mvrv_z"])
        scores["sopr"] = _apply_rules(sopr, ONCHAIN_RULES["sopr"])
        scores["nupl"] = _apply_rules(nupl, ONCHAIN_RULES["nupl"])
        scores["puell"] = _apply_rules(puell, ONCHAIN_RULES["puell"])
        scores["rhodl"] = _apply_rules(rhodl, ONCHAIN_RULES["rhodl"])

        cycle_score = sum(
            scores[k] * w for k, w in ONCHAIN_WEIGHTS.items()
        )

        if cycle_score > 0.4:
            phase = "ACCUMULATION"
        elif cycle_score > 0.1:
            phase = "MARKUP"
        elif cycle_score > -0.1:
            phase = "DISTRIBUTION"
        else:
            phase = "MARKDOWN"

        return OnChainScore(
            mvrv_z=mvrv_z,
            sopr=sopr,
            nupl=nupl,
            puell=puell,
            rhodl=rhodl,
            cycle_phase=phase,
            cycle_score=round(cycle_score, 4),
        )

    async def _predict_long(self, symbol: str) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=14)
        rows = await self.db.get_all_onchain_metrics_since(since)
        metrics = {}
        if rows:
            df = pd.DataFrame(rows, columns=["time", "metric_name", "value"])
            df = df.sort_values("time")
            latest = df.groupby("metric_name").last()["value"].to_dict()
            metrics = {k: _to_val(v) for k, v in latest.items()}

        mvrv_z = metrics.get("mvrv_z_score")
        mvrv_text = ""
        if mvrv_z is not None:
            if mvrv_z < 0.5:
                mvrv_text = "недооценён"
            elif mvrv_z < 3.0:
                mvrv_text = "справедливая оценка"
            elif mvrv_z < 7.0:
                mvrv_text = "переоценён"
            else:
                mvrv_text = "экстремально переоценён"

        since_1500d = datetime.now(timezone.utc) - timedelta(days=1500)
        rows_prices = await self.db.get_daily_candles_since(symbol, since_1500d)
        price_vs_200w = None
        price_vs_200w_text = ""
        if rows_prices and len(rows_prices) >= 200:
            df_p = pd.DataFrame(rows_prices, columns=["time", "close"])
            df_p.set_index("time", inplace=True)
            daily = df_p["close"].dropna().astype(float)
            ma200w = daily.rolling(200).mean()
            current_price = float(daily.iloc[-1])
            ma200w_val = float(ma200w.iloc[-1])
            price_vs_200w = round((current_price - ma200w_val) / ma200w_val, 4)
            if price_vs_200w > 0:
                price_vs_200w_text = f"цена на +{abs(price_vs_200w)*100:.0f}% выше MA — бычий тренд"
            else:
                price_vs_200w_text = f"цена на {price_vs_200w*100:.0f}% ниже MA — медвежий тренд"

        genesis = datetime(2009, 1, 3, tzinfo=timezone.utc)
        halving_interval = timedelta(seconds=210000 * 600)
        now = datetime.now(timezone.utc)
        n = int((now - genesis).total_seconds() / halving_interval.total_seconds())
        last_halving = genesis + n * halving_interval
        next_halving = genesis + (n + 1) * halving_interval
        halving_days = max(0, (next_halving - now).days)

        sthsopr = metrics.get("sthsopr")
        reserve_risk = metrics.get("reserve_risk")

        return {
            "mvrv_z": mvrv_z,
            "mvrv_interpretation": mvrv_text,
            "price_vs_200w_ma": price_vs_200w,
            "price_vs_200w_ma_text": price_vs_200w_text,
            "halving_days": halving_days,
            "sthsopr": sthsopr,
            "reserve_risk": reserve_risk,
        }
