import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/doc_poc"
    SYNC_DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/doc_poc"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    HISTORY_MAX_MESSAGES: int = 30
    MAX_MESSAGE_CHARS: int = 4000

    # Stage 3 Upload & Ingestion settings
    UPLOAD_DIR: str = "/data/uploads"
    MAX_UPLOAD_MB: int = 50
    MAX_FILES_PER_CONVERSATION: int = 10
    MAX_FILES_PER_REQUEST: int = 5
    INGEST_FAKE_DELAY_SECONDS: int = 0

    # Stage 4 Direct Mode settings
    DIRECT_MAX_PAGES: int = 40
    DIRECT_MAX_MB: int = 20
    DIRECT_MAX_TOTAL_TOKENS: int = 300000
    GEMINI_FILE_UPLOAD_TIMEOUT_SECONDS: int = 30
    CSV_MAX_ROWS_DIRECT: int = 200

    # Stage 5 Docling Parsing settings
    DOCLING_URL: str = "http://docling:5001"
    DOCLING_MEM_LIMIT: str = "3500M"
    PARSE_MODE: str = "rag_only"
    PARSE_BATCH_PAGES: int = 10
    PARSE_CONCURRENCY: int = 1
    PARSE_TIMEOUT_SECONDS: int = 300
    PARSE_OCR_ENABLED: bool = True
    PARSE_MIN_CHARS_PER_PAGE: int = 50

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
