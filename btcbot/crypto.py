import json
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from loguru import logger


class TONVerifier:
    _session: Optional[aiohttp.ClientSession] = None

    def __init__(self, api_url: str, api_key: str = ""):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

    async def _get_session(self) -> aiohttp.ClientSession:
        if TONVerifier._session is None or TONVerifier._session.closed:
            TONVerifier._session = aiohttp.ClientSession()
        return TONVerifier._session

    async def find_incoming_payment(
        self,
        recipient: str,
        expected_amount_nano: int,
        expected_comment: str,
        since: datetime,
    ) -> Optional[dict]:
        """Scan recent incoming transactions to find matching payment."""
        try:
            url = f"{self.api_url}/transactions"
            params = {"account": recipient, "limit": 30}
            headers = {}
            if self.api_key:
                headers["X-Api-Key"] = self.api_key

            session = await self._get_session()
            async with session.get(url, params=params, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    logger.warning("TONCenter API error {}: {}", resp.status, await resp.text())
                    return None
                data = await resp.json()
                txs = data.get("transactions", [])

                for tx in txs:
                    tx_time = datetime.fromtimestamp(tx.get("utime", 0), tz=timezone.utc)
                    if tx_time < since:
                        continue
                    in_msg = tx.get("in_msg", {})
                    if not in_msg or in_msg.get("destination") != recipient:
                        continue
                    value = int(in_msg.get("value", "0"))
                    if value != expected_amount_nano:
                        continue
                    raw_comment = in_msg.get("message", "")
                    if expected_comment in raw_comment:
                        tx_hash = tx.get("hash") or tx.get("transaction_id", {}).get("hash", "")
                        return {
                            "tx_hash": tx_hash,
                            "time": tx_time.isoformat(),
                            "amount": value,
                            "source": in_msg.get("source", ""),
                        }
        except Exception as e:
            logger.error("TONCenter scan error: {}", e)
        return None

    async def verify_transaction(
        self, tx_hash: str, recipient: str, expected_amount_nano: int
    ) -> bool:
        """Verify a specific transaction hash."""
        try:
            url = f"{self.api_url}/transactions/{tx_hash}"
            headers = {}
            if self.api_key:
                headers["X-Api-Key"] = self.api_key

            session = await self._get_session()
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                txs = data.get("transactions", [])
                for tx in txs:
                    in_msg = tx.get("in_msg", {})
                    if in_msg.get("destination") == recipient:
                        value = int(in_msg.get("value", "0"))
                        return value >= expected_amount_nano
        except Exception as e:
            logger.error("TONCenter tx verify error: {}", e)
        return False


def nano_to_ton(nano: int) -> float:
    return nano / 1_000_000_000


def ton_to_nano(ton: float) -> int:
    return int(ton * 1_000_000_000)
