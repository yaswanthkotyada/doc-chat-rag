from pydantic import BaseModel


class HealthResponse(BaseModel):
    api: str
    db: str
    pgvector: str
    gemini_key_configured: bool
    docling: str = "unreachable"

