import asyncio
import pytest
from btcbot.utils import safe_gather


class TestSafeGather:
    @pytest.mark.asyncio
    async def test_all_succeed(self):
        async def ok():
            return 42
        results = await safe_gather(ok(), ok(), log_prefix="test")
        assert results == [42, 42]

    @pytest.mark.asyncio
    async def test_one_fails_replaced_with_none(self):
        async def ok():
            return "data"
        async def fail():
            raise ValueError("boom")
        results = await safe_gather(ok(), fail(), log_prefix="test")
        assert results[0] == "data"
        assert results[1] is None

    @pytest.mark.asyncio
    async def test_all_fail(self):
        async def fail():
            raise RuntimeError("err")
        results = await safe_gather(fail(), fail(), log_prefix="test")
        assert results == [None, None]

    @pytest.mark.asyncio
    async def test_results_order_preserved(self):
        async def a():
            return 1
        async def b():
            return 2
        async def c():
            return 3
        results = await safe_gather(a(), b(), c(), log_prefix="test")
        assert results == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_empty_coros(self):
        results = await safe_gather(log_prefix="test")
        assert results == []

    @pytest.mark.asyncio
    async def test_mixed_types(self):
        async def int_():
            return 1
        async def float_():
            return 1.0
        async def str_():
            return "s"
        async def none_():
            return None
        results = await safe_gather(int_(), float_(), str_(), none_(), log_prefix="test")
        assert results == [1, 1.0, "s", None]

    @pytest.mark.asyncio
    async def test_cancelled_error_is_logged(self):
        async def cancelled():
            raise asyncio.CancelledError()
        results = await safe_gather(cancelled(), log_prefix="test")
        assert results == [None]
