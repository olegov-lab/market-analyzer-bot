from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

    telegram_bot_token: str
    database_url: str = "postgresql://postgres:postgres@postgres:5432/btcbot"
    redis_url: str = "redis://redis:6379/0"
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"
    coingecko_api_url: str = "https://api.coingecko.com/api/v3"
    opencode_go_api_key: str = ""
    opencode_go_endpoint: str = "https://opencode.ai/zen/go/v1"
    miniapp_url: str = "https://your-server.com/miniapp"
    ton_recipient_wallet: str = ""
    ton_pro_price_ton: float = 0.5
    ton_pro_plus_price_ton: float = 1.0
    toncenter_api_url: str = "https://toncenter.com/api/v3"
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = "minimax/minimax-m2.5:free"
    db_pool_min: int = 1
    db_pool_max: int = 5

    @property
    def miniapp_url_normalized(self) -> str:
        url = self.miniapp_url.rstrip("/")
        return url + "/"


settings = Settings()
