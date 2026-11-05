import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/doc_poc"
    SYNC_DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/doc_poc"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    HISTORY_MAX_MESSAGES: int = 30
    MAX_MESSAGE_CHARS: int = 4000

    # Stage 3 Upload & Ingestion settings
    UPLOAD_DIR: str = "/data/uploads"
    MAX_UPLOAD_MB: int = 50
    MAX_FILES_PER_CONVERSATION: int = 10
    MAX_FILES_PER_REQUEST: int = 5
    INGEST_FAKE_DELAY_SECONDS: int = 0

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
