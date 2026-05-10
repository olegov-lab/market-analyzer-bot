import re

_STRIP_RU = re.compile(r"(а|я|е|ё|и|й|о|у|ы|ь|ю|)(ть|тся|лся|лась|ли|л|ла|ло|в|вши|вшись|ему|им|ыми|их|ой|ую|ая|яя|ее|ие|ые|ого|его|ому|ему)$")
_STRIP_EN = re.compile(r"(ing|ed|ly|es|s|tion|ment|ness|able|ible|ive)$")

BULLISH_KEYWORDS = [
    "surge", "rally", "gain", "bull", "buy", "high", "growth", "record",
    "accumulate", "institutional", "etf", "adopt", "upgrade", "partner",
    "inflow", "break", "hold", "support", "momentum", "optimist",
    "rise", "up", "green", "profit", "positive", "upside", "breakout",
    "boost", "recover", "influx", "all-time", "ath", "moon", "pump",
    "рост", "бычий", "накопление", "покупк", "рекорд", "приток",
    "институциональн", "восстановлени", "прорыв", "уверенность",
    "растет", "вырос", "дорожает", "подорожа", "взлет", "увеличени",
    "прибыль", "позитив", "зелен", "восходящ", "бычий", "бычь",
    "накопл", "ралли", "профицит", "превыс", "доход",
]

BEARISH_KEYWORDS = [
    "loss", "drop", "fall", "crash", "bear", "sell", "decline",
    "purge", "ban", "hack", "fraud", "regulat", "worry", "fear",
    "liquidate", "downgrade", "revers", "resist", "panic", "capitul",
    "down", "red", "debt", "risk", "slump",
    "plunge", "dip", "correction", "bearish", "fud", "scam", "bubble",
    "падени", "медвежий", "потер", "слив", "страх", "обвал",
    "ликвидаци", "запрет", "мошенничеств", "регулятор", "паник",
    "падает", "упал", "дешеве", "подешев", "обруш", "снижени",
    "убыток", "долг", "риск", "волатиль", "коррекци", "пузырь",
    "отток", "дефицит", "кризис", "рецесси", "санкци", "блокировк",
]


def _stem_ru(word: str) -> str:
    return _STRIP_RU.sub("", word, 1)


def _stem_en(word: str) -> str:
    return _STRIP_EN.sub("", word, 1)


def _normalize(text: str) -> str:
    words = re.findall(r"[а-яёa-z]+", text.lower())
    stems = set()
    for w in words:
        if re.match(r"^[а-яё]", w):
            stems.add(_stem_ru(w))
        else:
            stems.add(_stem_en(w))
    return " ".join(stems)


def _keyword_match(norm: str, keyword: str) -> bool:
    if len(keyword) <= 3:
        return re.search(rf"(?<![a-zа-яё]){re.escape(keyword)}(?![a-zа-яё])", norm) is not None
    return keyword in norm


def classify_sentiment(title: str) -> str:
    norm = _normalize(title)
    bull_score = sum(1 for kw in BULLISH_KEYWORDS if _keyword_match(norm, kw))
    bear_score = sum(1 for kw in BEARISH_KEYWORDS if _keyword_match(norm, kw))
    if bull_score > bear_score:
        return "bullish"
    elif bear_score > bull_score:
        return "bearish"
    return "neutral"
