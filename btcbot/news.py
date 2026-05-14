import json
import xml.etree.ElementTree as ET

import aiohttp

from btcbot.sentiment import classify_sentiment

NEWS_CACHE_TTL = 300
RSS_URL = "https://news.google.com/rss/search?q=bitcoin&hl=ru&gl=RU&ceid=RU:ru"

_http_session: aiohttp.ClientSession = None


async def _get_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


async def fetch_news(redis_client) -> list:
    cached = await redis_client.get("btc:news")
    if cached:
        return json.loads(cached)

    try:
        session = await _get_session()
        async with session.get(RSS_URL) as resp:
            if resp.status != 200:
                return []
            xml_data = await resp.text()
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")[:10]
            articles = []
            for item in items:
                title_el = item.find("title")
                link_el = item.find("link")
                source_el = item.find("source")
                title = title_el.text if title_el is not None else ""
                url = link_el.text if link_el is not None else ""
                source = source_el.text if source_el is not None else ""
                if not title or not url:
                    continue
                articles.append({"title": title, "source": source, "url": url})
                if len(articles) >= 5:
                    break
            for a in articles:
                a["sentiment"] = classify_sentiment(a["title"])
            await redis_client.set("btc:news", json.dumps(articles), ex=NEWS_CACHE_TTL)
            return articles
    except Exception:
        return []


def build_sentiment_summary(articles: list) -> dict:
    bull_count = sum(1 for a in articles if a.get("sentiment") == "bullish")
    bear_count = sum(1 for a in articles if a.get("sentiment") == "bearish")
    neutral_count = sum(1 for a in articles if a.get("sentiment") == "neutral")
    total = len(articles)

    if bull_count > bear_count:
        mood = "bullish"
    elif bear_count > bull_count:
        mood = "bearish"
    else:
        mood = "neutral"

    return {
        "articles": articles,
        "sentiment": {
            "bullish": bull_count,
            "bearish": bear_count,
            "neutral": neutral_count,
            "total": total,
            "mood": mood,
        },
    }


def build_market_brain_comment(bull_count: int, bear_count: int, total: int) -> str:
    ratio = bull_count / total if total else 0
    if ratio >= 0.6:
        return (
            "Преобладает позитив — институциональные потоки и накопление "
            "перевешивают локальные риски. В краткосрочной перспективе — бычий уклон."
        )
    elif total and bear_count / total >= 0.6:
        return (
            "Доминируют негативные заголовки — бегство от риска и "
            "регуляторное давление. Краткосрочно — медвежий уклон."
        )
    else:
        return (
            "Смешанный фон — позитивные и негативные сигналы "
            "уравновешивают друг друга. Рынок в зоне неопределённости."
        )
