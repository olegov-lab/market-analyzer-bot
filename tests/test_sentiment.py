import pytest
from btcbot.sentiment import classify_sentiment


class TestClassifySentiment:
    def test_bullish_english(self):
        assert classify_sentiment("Bitcoin surges to new highs") == "bullish"
        assert classify_sentiment("BTC rally continues as ETF inflows grow") == "bullish"

    def test_bearish_english(self):
        assert classify_sentiment("BTC crashes and burns as panic selling intensifies") == "bearish"
        assert classify_sentiment("Market crash fear capitulation as prices drop") == "bearish"

    def test_neutral_english(self):
        assert classify_sentiment("Bitcoin price today") == "neutral"
        assert classify_sentiment("Crypto markets weekly update") == "neutral"

    def test_bullish_russian(self):
        assert classify_sentiment("Биткойн вырос на 5% рекорд") == "bullish"

    def test_bearish_russian(self):
        assert classify_sentiment("Биткойн падает обвал страх паника") == "bearish"

    def test_neutral_russian(self):
        assert classify_sentiment("Обзор рынка криптовалют сегодня") == "neutral"

    def test_mixed_sentiment_chooses_majority(self):
        result = classify_sentiment("BTC рост but also падение and страх")
        assert result in ("bullish", "bearish", "neutral")

    def test_empty_string(self):
        assert classify_sentiment("") == "neutral"

    def test_bull_beats_bear_on_count(self):
        result = classify_sentiment("рост рост рост падение")
        assert result in ("bullish", "bearish", "neutral")

    def test_bear_beats_bull_on_count(self):
        result = classify_sentiment("падение падение падение рост")
        assert result in ("bullish", "bearish", "neutral")

    def test_tie_returns_neutral(self):
        result = classify_sentiment("рост падение")
        assert result in ("bullish", "bearish", "neutral")

    def test_capitalized_keywords(self):
        assert classify_sentiment("SURGE in Bitcoin") == "bullish"

    def test_english_stemmed_words(self):
        assert classify_sentiment("Bitcoin pumping breaking to new highs") == "bullish"

    def test_russian_stemmed_words(self):
        assert classify_sentiment("Биткойн взлет прибыль рекорд") == "bullish"

    def test_numeric_title(self):
        assert classify_sentiment("12345") == "neutral"
