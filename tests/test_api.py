import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api import _fast_or_none


class TestFastOrNone:
    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        async def ok():
            return 42

        result = await _fast_or_none(ok(), timeout=2.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        async def slow():
            import asyncio
            await asyncio.sleep(10)
            return 42

        result = await _fast_or_none(slow(), timeout=0.01)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        async def fail():
            raise ValueError("boom")

        result = await _fast_or_none(fail(), timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_none_return(self):
        async def none_func():
            return None

        result = await _fast_or_none(none_func(), timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_empty_dict(self):
        async def empty_dict():
            return {}

        result = await _fast_or_none(empty_dict(), timeout=2.0)
        assert result == {}

    @pytest.mark.asyncio
    async def test_fast_response_passes_through(self):
        async def fast():
            return {"data": "ok"}

        result = await _fast_or_none(fast(), timeout=5.0)
        assert result == {"data": "ok"}


class TestRunAskTask:
    @pytest.mark.asyncio
    async def test_successful_task_sets_done(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=100000.0)

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "Ответ Market-Brain"
            redis_mock.get = AsyncMock(return_value=None)

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_1", "почём биток?", 123)

            call_args = redis_mock.setex.call_args_list[-1]
            args = call_args[0]
            assert args[0] == "btc:ask:test_task_1"
            data = json.loads(args[2])
            assert data["status"] == "done"
            assert data["result"] == "Ответ Market-Brain"

    @pytest.mark.asyncio
    async def test_agent_error_sets_error_status(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=100000.0)

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "[Agent error: timeout]"
            redis_mock.get = AsyncMock(return_value=None)

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_2", "question", 123)

            call_args = redis_mock.setex.call_args_list[-1]
            args = call_args[0]
            data = json.loads(args[2])
            assert data["status"] == "error"
            assert "unavailable" in data["result"]

    @pytest.mark.asyncio
    async def test_agent_returns_none_sets_error(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=100000.0)

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = None
            redis_mock.get = AsyncMock(return_value=None)

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_3", "question", 123)

            call_args = redis_mock.setex.call_args_list[-1]
            args = call_args[0]
            data = json.loads(args[2])
            assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_db_price_none_does_not_crash(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=None)

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "OK"
            redis_mock.get = AsyncMock(return_value=None)

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_4", "q", 123)

            call_args = redis_mock.setex.call_args_list[-1]
            args = call_args[0]
            data = json.loads(args[2])
            assert data["status"] == "done"

    @pytest.mark.asyncio
    async def test_redis_indicators_cached_adds_context(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=95000.0)

        ind_data = json.dumps({"rsi": 55.0, "ma_50": 93000, "ma_200": 90000})

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "Ответ с контекстом"
            redis_mock.get = AsyncMock(return_value=ind_data)

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_5", "q", 123)

            prompt = mock_ask.call_args[0][1]
            assert "95,000" in prompt
            assert "RSI" in prompt
            assert "MA50" in prompt

    @pytest.mark.asyncio
    async def test_redis_exception_does_not_crash(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        redis_mock.get = AsyncMock(side_effect=ConnectionError("redis down"))
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=100000.0)

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "OK sans cache"

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_6", "q", 123)

            call_args = redis_mock.setex.call_args_list[-1]
            args = call_args[0]
            data = json.loads(args[2])
            assert data["status"] == "done"
            assert data["result"] == "OK sans cache"

    @pytest.mark.asyncio
    async def test_no_redis_sets_error_via_exception(self):
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=100000.0)

        with patch("backend.api.redis_client", None), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "Works without redis"

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_7", "q", 123)
            # No redis → no setex calls → no error

    @pytest.mark.asyncio
    async def test_running_status_set_at_start(self):
        redis_mock = AsyncMock()
        redis_mock.setex = AsyncMock()
        db_mock = AsyncMock()
        db_mock.get_latest_price = AsyncMock(return_value=100000.0)

        with patch("backend.api.redis_client", redis_mock), \
             patch("backend.api.db", db_mock), \
             patch("backend.api.ask_agent") as mock_ask:
            mock_ask.return_value = "OK"
            redis_mock.get = AsyncMock(return_value=None)

            from backend.api import _run_ask_task
            await _run_ask_task("test_task_8", "q", 123)

            first_call = redis_mock.setex.call_args_list[0]
            args = first_call[0]
            data = json.loads(args[2])
            assert data["status"] == "running"
