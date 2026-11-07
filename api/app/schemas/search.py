import uuid
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Query text to search for")
    mode: str = Field("hybrid", description="'vector' | 'keyword' | 'hybrid'")
    limit: int = Field(10, ge=1, le=50, description="Max results to return (1-50)")
    document_ids: Optional[List[uuid.UUID]] = Field(None, description="Optional document filter")
    conversation_id: Optional[uuid.UUID] = Field(None, description="Optional conversation filter")


class SearchResultItemResponse(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    document_filename: str
    text: str
    page_start: int
    page_end: int
    heading_path: List[str] = []
    chunk_type: str = "text"
    token_count: int = 0
    score: float
    vector_score: Optional[float] = None
    vector_rank: Optional[int] = None
    keyword_score: Optional[float] = None
    keyword_rank: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class SearchDebugResponse(BaseModel):
    query: str
    mode: str
    limit: int
    total_results: int
    duration_ms: float
    items: List[SearchResultItemResponse] = []

    model_config = ConfigDict(from_attributes=True)
