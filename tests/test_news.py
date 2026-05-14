import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from btcbot.news import build_sentiment_summary, build_market_brain_comment, fetch_news


class TestBuildSentimentSummary:
    def test_all_bullish(self):
        articles = [
            {"title": "Bullish", "sentiment": "bullish"},
            {"title": "Bullish2", "sentiment": "bullish"},
            {"title": "Bullish3", "sentiment": "bullish"},
        ]
        result = build_sentiment_summary(articles)
        assert result["sentiment"]["bullish"] == 3
        assert result["sentiment"]["bearish"] == 0
        assert result["sentiment"]["mood"] == "bullish"

    def test_all_bearish(self):
        articles = [
            {"title": "Bear", "sentiment": "bearish"},
            {"title": "Bear2", "sentiment": "bearish"},
        ]
        result = build_sentiment_summary(articles)
        assert result["sentiment"]["bearish"] == 2
        assert result["sentiment"]["mood"] == "bearish"

    def test_mixed_tie(self):
        articles = [
            {"title": "Bull", "sentiment": "bullish"},
            {"title": "Bear", "sentiment": "bearish"},
            {"title": "Neut", "sentiment": "neutral"},
        ]
        result = build_sentiment_summary(articles)
        assert result["sentiment"]["mood"] == "neutral"

    def test_empty_list(self):
        result = build_sentiment_summary([])
        assert result["sentiment"]["total"] == 0

    def test_articles_included(self):
        articles = [{"title": "Test", "sentiment": "bullish", "source": "src", "url": "url"}]
        result = build_sentiment_summary(articles)
        assert result["articles"] is articles


class TestBuildMarketBrainComment:
    def test_bullish_comment(self):
        msg = build_market_brain_comment(bull_count=4, bear_count=1, total=5)
        assert "позитив" in msg.lower()

    def test_bearish_comment(self):
        msg = build_market_brain_comment(bull_count=0, bear_count=5, total=5)
        assert "негатив" in msg.lower()

    def test_mixed_comment(self):
        msg = build_market_brain_comment(bull_count=2, bear_count=2, total=4)
        assert "смешан" in msg.lower()

    def test_zero_total(self):
        msg = build_market_brain_comment(bull_count=0, bear_count=0, total=0)
        assert "смешан" in msg.lower()

    def test_exact_60_percent(self):
        msg = build_market_brain_comment(bull_count=3, bear_count=2, total=5)
        assert "позитив" in msg.lower()


class TestFetchNews:
    @pytest.mark.asyncio
    async def test_returns_cached(self):
        mock_redis = AsyncMock()
        cached = [{"title": "Cached", "sentiment": "bullish"}]
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))
        result = await fetch_news(mock_redis)
        assert result == cached

    @pytest.mark.asyncio
    async def test_empty_cache_returns_empty_on_http_error(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        with patch("btcbot.news._get_session") as mock_session:
            mock_resp = MagicMock()
            mock_resp.status = 500
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock()
            mock_sess = MagicMock()
            mock_sess.get = MagicMock(return_value=mock_resp)
            mock_sess.closed = False
            mock_session.return_value = mock_sess
            result = await fetch_news(mock_redis)
            assert result == []
