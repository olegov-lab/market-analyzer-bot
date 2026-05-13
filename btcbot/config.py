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

    @property
    def miniapp_url_normalized(self) -> str:
        url = self.miniapp_url.rstrip("/")
        return url + "/"


settings = Settings()
