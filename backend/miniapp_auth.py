import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def verify_telegram_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    parsed = dict(parse_qsl(init_data))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    auth_date = int(parsed.get("auth_date", 0))
    if auth_date and time.time() - auth_date > max_age:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )

    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()

    calc_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    user = json.loads(parsed.get("user", "{}"))
    return user
