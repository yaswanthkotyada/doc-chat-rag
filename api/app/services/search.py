"""
Stage 6 - Milestone 4: Search Service.

Implements Vector search (cosine similarity via pgvector),
Keyword search (full-text search using tsvector and websearch_to_tsquery),
and Hybrid search using Reciprocal Rank Fusion (RRF).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk, Document
from app.services.embeddings import get_embedding_service


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SearchResultItem:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    document_filename: str
    text: str
    page_start: int
    page_end: int
    heading_path: List[str]
    chunk_type: str
    token_count: int
    score: float
    vector_score: Optional[float] = None
    vector_rank: Optional[int] = None
    keyword_score: Optional[float] = None
    keyword_rank: Optional[int] = None


@dataclass
class SearchResponse:
    query: str
    mode: str
    limit: int
    total_results: int
    duration_ms: float
    items: List[SearchResultItem]


# ---------------------------------------------------------------------------
# Search Queries Execution
# ---------------------------------------------------------------------------

async def _search_vector(
    db: AsyncSession,
    query_vector: List[float],
    limit: int,
    document_ids: Optional[List[uuid.UUID]] = None,
    conversation_id: Optional[uuid.UUID] = None,
) -> List[Dict[str, Any]]:
    """Execute vector cosine distance query and return ranked candidates."""
    distance_col = Chunk.embedding.cosine_distance(query_vector)
    score_col = (1.0 - distance_col).label("vector_score")

    stmt = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id,
            Chunk.chunk_index,
            Document.filename.label("document_filename"),
            Chunk.text,
            Chunk.page_start,
            Chunk.page_end,
            Chunk.heading_path,
            Chunk.chunk_type,
            Chunk.token_count,
            score_col,
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.embedding.isnot(None))
    )

    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    if conversation_id:
        stmt = stmt.where(Document.conversation_id == conversation_id)

    stmt = stmt.order_by(distance_col.asc()).limit(limit)

    result = await db.execute(stmt)
    rows = result.mappings().all()

    candidates: List[Dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        item = dict(row)
        item["vector_rank"] = rank
        candidates.append(item)
    return candidates


async def _search_keyword(
    db: AsyncSession,
    query_text: str,
    limit: int,
    document_ids: Optional[List[uuid.UUID]] = None,
    conversation_id: Optional[uuid.UUID] = None,
) -> List[Dict[str, Any]]:
    """Execute Postgres tsvector keyword query using websearch_to_tsquery('simple')."""
    from sqlalchemy import func
    tsquery = func.websearch_to_tsquery("simple", query_text)
    rank_col = func.ts_rank(Chunk.tsv, tsquery).label("keyword_score")

    stmt = (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.document_id,
            Chunk.chunk_index,
            Document.filename.label("document_filename"),
            Chunk.text,
            Chunk.page_start,
            Chunk.page_end,
            Chunk.heading_path,
            Chunk.chunk_type,
            Chunk.token_count,
            rank_col,
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.tsv.op("@@")(tsquery))
    )

    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    if conversation_id:
        stmt = stmt.where(Document.conversation_id == conversation_id)

    stmt = stmt.order_by(rank_col.desc()).limit(limit)

    try:
        result = await db.execute(stmt)
        rows = result.mappings().all()
    except Exception:
        # If query cannot produce valid tsquery (e.g. only punctuation), return empty
        return []

    candidates: List[Dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        item = dict(row)
        item["keyword_rank"] = rank
        candidates.append(item)
    return candidates


# ---------------------------------------------------------------------------
# Public Search Function
# ---------------------------------------------------------------------------

async def search_chunks(
    db: AsyncSession,
    query: str,
    mode: str = "hybrid",
    limit: int = 10,
    document_ids: Optional[List[uuid.UUID]] = None,
    conversation_id: Optional[uuid.UUID] = None,
    rrf_k: int = 60,
) -> SearchResponse:
    """
    Search document chunks using vector, keyword, or hybrid RRF search.

    Args:
        db: Async database session.
        query: User search text.
        mode: 'vector' | 'keyword' | 'hybrid' (default: 'hybrid').
        limit: Max results to return (1..50).
        document_ids: Optional document filters.
        conversation_id: Optional conversation filter.
        rrf_k: Smoothing constant for Reciprocal Rank Fusion (default: 60).
    """
    trimmed = query.strip()
    if not trimmed:
        return SearchResponse(
            query=query,
            mode=mode,
            limit=limit,
            total_results=0,
            duration_ms=0.0,
            items=[],
        )

    start_time = time.monotonic()
    mode_lower = mode.lower()
    if mode_lower not in ("vector", "keyword", "hybrid"):
        mode_lower = "hybrid"

    # 1. Vector Search Mode
    if mode_lower == "vector":
        embedding_service = get_embedding_service()
        query_vector = await embedding_service.embed_query(trimmed)
        candidates = await _search_vector(
            db, query_vector, limit=limit,
            document_ids=document_ids, conversation_id=conversation_id
        )
        items = [
            SearchResultItem(
                chunk_id=c["chunk_id"],
                document_id=c["document_id"],
                chunk_index=c["chunk_index"],
                document_filename=c["document_filename"],
                text=c["text"],
                page_start=c["page_start"],
                page_end=c["page_end"],
                heading_path=c["heading_path"] or [],
                chunk_type=c["chunk_type"],
                token_count=c["token_count"],
                score=round(float(c["vector_score"]), 4),
                vector_score=round(float(c["vector_score"]), 4),
                vector_rank=c["vector_rank"],
            )
            for c in candidates
        ]

    # 2. Keyword Search Mode
    elif mode_lower == "keyword":
        candidates = await _search_keyword(
            db, trimmed, limit=limit,
            document_ids=document_ids, conversation_id=conversation_id
        )
        items = [
            SearchResultItem(
                chunk_id=c["chunk_id"],
                document_id=c["document_id"],
                chunk_index=c["chunk_index"],
                document_filename=c["document_filename"],
                text=c["text"],
                page_start=c["page_start"],
                page_end=c["page_end"],
                heading_path=c["heading_path"] or [],
                chunk_type=c["chunk_type"],
                token_count=c["token_count"],
                score=round(float(c["keyword_score"]), 4),
                keyword_score=round(float(c["keyword_score"]), 4),
                keyword_rank=c["keyword_rank"],
            )
            for c in candidates
        ]

    # 3. Hybrid Search Mode (Reciprocal Rank Fusion)
    else:
        k_candidates = max(limit * 2, 50)
        embedding_service = get_embedding_service()

        # Run vector embedding and candidates concurrently
        query_vector = await embedding_service.embed_query(trimmed)

        vector_candidates = await _search_vector(
            db, query_vector, limit=k_candidates,
            document_ids=document_ids, conversation_id=conversation_id
        )
        keyword_candidates = await _search_keyword(
            db, trimmed, limit=k_candidates,
            document_ids=document_ids, conversation_id=conversation_id
        )

        # Merge via Reciprocal Rank Fusion
        fused: Dict[uuid.UUID, Dict[str, Any]] = {}

        for c in vector_candidates:
            cid = c["chunk_id"]
            rrf_contrib = 1.0 / (rrf_k + c["vector_rank"])
            fused[cid] = {
                "base": c,
                "rrf_score": rrf_contrib,
                "vector_score": round(float(c["vector_score"]), 4),
                "vector_rank": c["vector_rank"],
                "keyword_score": None,
                "keyword_rank": None,
            }

        for c in keyword_candidates:
            cid = c["chunk_id"]
            rrf_contrib = 1.0 / (rrf_k + c["keyword_rank"])
            if cid in fused:
                fused[cid]["rrf_score"] += rrf_contrib
                fused[cid]["keyword_score"] = round(float(c["keyword_score"]), 4)
                fused[cid]["keyword_rank"] = c["keyword_rank"]
            else:
                fused[cid] = {
                    "base": c,
                    "rrf_score": rrf_contrib,
                    "vector_score": None,
                    "vector_rank": None,
                    "keyword_score": round(float(c["keyword_score"]), 4),
                    "keyword_rank": c["keyword_rank"],
                }

        # Sort by RRF score descending
        sorted_fused = sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)[:limit]

        items = [
            SearchResultItem(
                chunk_id=entry["base"]["chunk_id"],
                document_id=entry["base"]["document_id"],
                chunk_index=entry["base"]["chunk_index"],
                document_filename=entry["base"]["document_filename"],
                text=entry["base"]["text"],
                page_start=entry["base"]["page_start"],
                page_end=entry["base"]["page_end"],
                heading_path=entry["base"]["heading_path"] or [],
                chunk_type=entry["base"]["chunk_type"],
                token_count=entry["base"]["token_count"],
                score=round(entry["rrf_score"], 6),
                vector_score=entry["vector_score"],
                vector_rank=entry["vector_rank"],
                keyword_score=entry["keyword_score"],
                keyword_rank=entry["keyword_rank"],
            )
            for entry in sorted_fused
        ]

    duration_ms = round((time.monotonic() - start_time) * 1000, 2)
    return SearchResponse(
        query=query,
        mode=mode_lower,
        limit=limit,
        total_results=len(items),
        duration_ms=duration_ms,
        items=items,
    )
