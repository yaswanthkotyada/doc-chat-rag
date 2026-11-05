import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: str
    error: Optional[str] = None
    page_count: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    mode: Optional[str] = None
    meta: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
