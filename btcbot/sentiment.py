BULLISH_KEYWORDS = [
    "surge", "rally", "gain", "bull", "buy", "high", "growth", "record",
    "accumulate", "institutional", "etf", "adopt", "upgrade", "partner",
    "inflow", "break", "hold", "support", "momentum", "optimist",
    "рост", "бычий", "накопление", "покупк", "рекорд", "приток",
    "институциональн", "восстановлени", "прорыв", "уверенность",
]

BEARISH_KEYWORDS = [
    "loss", "drop", "fall", "crash", "bear", "sell", "low", "decline",
    "purge", "ban", "hack", "fraud", "regulat", "worry", "fear",
    "liquidate", "downgrade", "revers", "resist", "panic", "capitul",
    "падени", "медвежий", "потер", "слив", "страх", "обвал",
    "ликвидаци", "запрет", "мошенничеств", "регулятор", "паник",
]


def classify_sentiment(title: str) -> str:
    lower = title.lower()
    bull_score = sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
    bear_score = sum(1 for kw in BEARISH_KEYWORDS if kw in lower)
    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"
    return "neutral"
