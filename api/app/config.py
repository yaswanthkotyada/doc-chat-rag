import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/doc_poc"
    SYNC_DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/doc_poc"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    HISTORY_MAX_MESSAGES: int = 30
    MAX_MESSAGE_CHARS: int = 4000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def __init__(self, **values):
        super().__init__(**values)
        if not self.GEMINI_API_KEY:
            # Fallback check for alternate env var key
            self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("Gemini API Key") or ""


settings = Settings()

