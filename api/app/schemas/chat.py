import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID
    message: str = Field(default="", description="User message content")
    document_ids: Optional[List[uuid.UUID]] = Field(default=None, description="Optional document IDs to attach")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        trimmed = v.strip() if v else ""
        if len(trimmed) > settings.MAX_MESSAGE_CHARS:
            raise ValueError(f"Message exceeds maximum allowed length of {settings.MAX_MESSAGE_CHARS} characters.")
        return trimmed

    @model_validator(mode="after")
    def validate_content_or_documents(self) -> "ChatRequest":
        if not self.message and self.document_ids is not None and len(self.document_ids) == 0:
            raise ValueError("Message cannot be empty when no documents are attached.")
        return self
