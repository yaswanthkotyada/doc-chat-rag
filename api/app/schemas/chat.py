import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator

from app.config import settings


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID
    message: str = Field(..., description="User message content")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Message cannot be empty.")
        if len(v) > settings.MAX_MESSAGE_CHARS:
            raise ValueError(f"Message exceeds maximum allowed length of {settings.MAX_MESSAGE_CHARS} characters.")
        return trimmed
