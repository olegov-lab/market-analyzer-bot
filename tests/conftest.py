import sys
from unittest.mock import MagicMock, AsyncMock

import pytest

mock_asyncpg = MagicMock()
mock_asyncpg.Connection = MagicMock
mock_asyncpg.Record = MagicMock
sys.modules["asyncpg"] = mock_asyncpg


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.pool = MagicMock()
    db.pool.acquire = MagicMock()
    return db


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)
    return conn
