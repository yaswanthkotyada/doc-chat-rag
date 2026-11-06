import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
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

    # Parsing metadata (Stage 5)
    parse_status: Optional[str] = None
    parse_error: Optional[str] = None
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    parse_started_at: Optional[datetime] = None
    parse_finished_at: Optional[datetime] = None
    pages_parsed: Optional[int] = 0
    parse_options: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentParseSummary(BaseModel):
    total_warnings: int = 0
    low_text_pages: List[int] = []
    garbled_pages: List[int] = []
    pages_with_tables: int = 0
    pages_with_figures: int = 0
    total_characters: int = 0


class DocumentParseResponse(BaseModel):
    document_id: uuid.UUID
    parse_status: Optional[str] = None
    parse_error: Optional[str] = None
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    parse_started_at: Optional[datetime] = None
    parse_finished_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    pages_parsed: int = 0
    total_pages: Optional[int] = None
    parse_options: Optional[Dict[str, Any]] = None
    warnings_summary: Optional[DocumentParseSummary] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentPageSummary(BaseModel):
    id: uuid.UUID
    page_no: int
    char_count: int
    has_table: bool
    has_figure: bool
    ocr_used: Optional[bool] = None
    warnings: List[str] = []

    model_config = ConfigDict(from_attributes=True)


class DocumentPagesListResponse(BaseModel):
    items: List[DocumentPageSummary]
    total: int
    page: int
    limit: int
    total_pages: int


class DocumentPageDetail(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_no: int
    markdown: str
    plain_text: str
    char_count: int
    has_table: bool
    has_figure: bool
    ocr_used: Optional[bool] = None
    warnings: List[str] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

