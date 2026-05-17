"""CI/CD Smoke Test — проверяет, что БД и API отвечают под базовой нагрузкой.
Запускать перед каждым деплоем:
  pytest tests/test_smoke.py -v --timeout=30
"""
import os
import pytest
import httpx
import asyncio

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")


@pytest.mark.asyncio
async def test_health_returns_200():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE_URL}/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_btc_price_returns_data():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE_URL}/btc/price")
    assert r.status_code == 200
    data = r.json()
    assert "price" in data


@pytest.mark.asyncio
async def test_indicators_respond():
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{BASE_URL}/btc/indicators")
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert "rsi" in r.json()


@pytest.mark.asyncio
async def test_dashboard_bundle():
    endpoints = [
        "/miniapp/dashboard",
        "/miniapp/fear-greed",
        "/miniapp/consensus",
        "/miniapp/news",
        "/miniapp/volatility",
    ]
    async with httpx.AsyncClient(timeout=20) as client:
        tasks = [client.get(f"{BASE_URL}{ep}") for ep in endpoints]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
    ok = sum(1 for r in responses if isinstance(r, httpx.Response) and r.status_code < 500)
    assert ok >= 3, f"Only {ok}/5 endpoints healthy"


@pytest.mark.asyncio
async def test_game_endpoints():
    endpoints = [
        "/miniapp/game/state",
        "/miniapp/game/mining/state",
        "/miniapp/game/roulette/state",
        "/miniapp/game/achievements",
    ]
    async with httpx.AsyncClient(timeout=15) as client:
        tasks = [client.get(f"{BASE_URL}{ep}") for ep in endpoints]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
    ok = sum(1 for r in responses if isinstance(r, httpx.Response) and r.status_code < 500)
    assert ok >= 3, f"Only {ok}/4 game endpoints healthy"


@pytest.mark.asyncio
async def test_chart_data():
    async with httpx.AsyncClient(timeout=15) as client:
        for tf in ("1h", "4h", "1d"):
            r = await client.get(f"{BASE_URL}/miniapp/chart?timeframe={tf}&limit=20")
            assert r.status_code in (200, 401, 503)


@pytest.mark.asyncio
async def test_subscription_status():
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BASE_URL}/miniapp/subscription/status")
    assert r.status_code in (200, 401)


@pytest.mark.asyncio
async def test_concurrent_burst():
    """20 concurrent requests — базовая проверка пула соединений."""
    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [
            client.get(f"{BASE_URL}/miniapp/dashboard")
            for _ in range(20)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
    errors = sum(1 for r in responses if isinstance(r, Exception))
    non_200 = sum(1 for r in responses if isinstance(r, httpx.Response) and r.status_code >= 500)
    assert errors == 0, f"{errors} connection errors"
    assert non_200 == 0, f"{non_200} HTTP 500+ responses"
