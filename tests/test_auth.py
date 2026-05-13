import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from backend.miniapp_auth import verify_telegram_init_data


BOT_TOKEN = "123456:ABC-DEF"


def _make_init_data(user: dict, bot_token: str = BOT_TOKEN) -> str:
    data = {
        "query_id": "AAHdF6IQAAAAAN0XohDhr",
        "user": json.dumps(user),
        "auth_date": "1700000000",
        "hash": "",
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()) if k != "hash")
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return "&".join(f"{k}={v}" for k, v in data.items())


class TestVerifyTelegramInitData:
    def test_valid_init_data(self):
        user = {"id": 12345, "first_name": "Alice"}
        init_data = _make_init_data(user)
        result = verify_telegram_init_data(init_data, BOT_TOKEN)
        assert result is not None
        assert result["id"] == 12345
        assert result["first_name"] == "Alice"

    def test_invalid_hash(self):
        user = {"id": 12345}
        init_data = _make_init_data(user)
        tampered = init_data.replace(init_data[-8:], "f" * 8)
        result = verify_telegram_init_data(tampered, BOT_TOKEN)
        assert result is None

    def test_missing_hash(self):
        result = verify_telegram_init_data("user=%7B%22id%22%3A1%7D&auth_date=1", BOT_TOKEN)
        assert result is None

    def test_empty_string(self):
        result = verify_telegram_init_data("", BOT_TOKEN)
        assert result is None

    def test_different_bot_token_fails(self):
        user = {"id": 12345}
        init_data = _make_init_data(user, BOT_TOKEN)
        result = verify_telegram_init_data(init_data, "other_token")
        assert result is None
