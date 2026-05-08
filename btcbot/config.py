from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token: str
    glassnode_api_key: str = ""
    coinglass_api_key: str = ""
    coinmarketcap_api_key: str = ""
    database_url: str = "postgresql://postgres:postgres@localhost:5432/btcbot"
    redis_url: str = "redis://localhost:6379/0"
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"
    coingecko_api_url: str = "https://api.coingecko.com/api/v3"
    glassnode_api_url: str = "https://api.glassnode.com/v1"
    coinglass_api_url: str = "https://open-api.coinglass.com/api/pro/v1"
    ollama_host: str = "http://localhost:11434"


settings = Settings()
