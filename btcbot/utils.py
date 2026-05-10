import asyncio

from loguru import logger


async def safe_gather(*coros, log_prefix: str = "") -> list:
    results = await asyncio.gather(*coros, return_exceptions=True)
    cleaned = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            logger.error("{}Task {} failed: {}", log_prefix, i, r)
            cleaned.append(None)
        else:
            cleaned.append(r)
    return cleaned
