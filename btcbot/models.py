from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PriceRecord(BaseModel):
    time: datetime
    symbol: str
    price: float
    volume: float
    source: str


class Candle(BaseModel):
    time: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorSet(BaseModel):
    time: datetime
    symbol: str
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    ma_50: Optional[float] = None
    ma_100: Optional[float] = None
    ma_200: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    obv: Optional[float] = None


class Prediction(BaseModel):
    time: datetime
    horizon: str
    price_min: float
    price_max: float
    direction: str
    confidence: float
    meta: dict = {}


class Alert(BaseModel):
    user_id: int
    alert_type: str
    price: Optional[float] = None
    message: str
    sent: bool = False


class User(BaseModel):
    user_id: int
    username: Optional[str] = None
    created_at: datetime
    is_active: bool = True
    timezone: str = "UTC"


class Subscription(BaseModel):
    user_id: int
    symbol: str
    interval: str = "15m"
    alert_types: list[str] = []


class OnchainMetric(BaseModel):
    time: datetime
    metric_name: str
    value: float
    source: str


class LiquidityZone(BaseModel):
    type: str
    price: float
    description: str


class OnChainScore(BaseModel):
    mvrv_z: Optional[float] = None
    sopr: Optional[float] = None
    nupl: Optional[float] = None
    puell: Optional[float] = None
    rhodl: Optional[float] = None
    cycle_phase: str = "UNKNOWN"
    cycle_score: float = 0.0


class VolatilityData(BaseModel):
    current: float
    classification: str
    bb_width_pct: float
    atr_pct: float
    percentile: float
    history: list[float]


class MetcalfeCorridor(BaseModel):
    time: datetime
    active_addresses: int
    metcalfe_price: float
    upper_band: float
    lower_band: float
    actual_price: float
    deviation_pct: float
    coefficient_k: float
    signal: str  # overvalued / fair / undervalued
    history: list[dict] = []
    dataset_days: int = 0
