from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_token: SecretStr = Field(alias="TELEGRAM_TOKEN")
    auth_password: SecretStr = Field(alias="AUTH_PASSWORD")
    database_path: Path = Field(default=Path("data/bot.sqlite3"), alias="DATABASE_PATH")
    ozon_storage_state: Path = Field(default=Path("storage/ozon_state.json"), alias="OZON_STORAGE_STATE")
    ozon_reviews_url: str = Field(default="https://seller.ozon.ru/app/reviews", alias="OZON_REVIEWS_URL")
    poll_interval_seconds: int = Field(default=300, ge=30, alias="POLL_INTERVAL_SECONDS")
    max_reply_length: int = Field(default=1000, ge=50, le=4000, alias="MAX_REPLY_LENGTH")
    llm_api_key: SecretStr | None = Field(default=None, alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://generativelanguage.googleapis.com/v1beta/openai/", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gemini-2.0-flash", alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(default=30, gt=0, alias="LLM_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.ozon_storage_state.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    try:
        settings = Settings()
    except ValidationError as exc:
        raise RuntimeError("Проверьте TELEGRAM_TOKEN и AUTH_PASSWORD в .env") from exc
    settings.ensure_directories()
    return settings
