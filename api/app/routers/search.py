import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.search import SearchDebugResponse, SearchRequest, SearchResultItemResponse
from app.services.search import search_chunks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/debug", response_model=SearchDebugResponse)
async def search_debug_endpoint(
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Search indexed document chunks across vector, keyword, or hybrid RRF mode.
    Returns ranked chunks with individual vector & keyword score breakdowns.
    """
    try:
        response = await search_chunks(
            db=db,
            query=payload.query,
            mode=payload.mode,
            limit=payload.limit,
            document_ids=payload.document_ids,
            conversation_id=payload.conversation_id,
        )

        return SearchDebugResponse(
            query=response.query,
            mode=response.mode,
            limit=response.limit,
            total_results=response.total_results,
            duration_ms=response.duration_ms,
            items=[
                SearchResultItemResponse(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    chunk_index=item.chunk_index,
                    document_filename=item.document_filename,
                    text=item.text,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    heading_path=item.heading_path,
                    chunk_type=item.chunk_type,
                    token_count=item.token_count,
                    score=item.score,
                    vector_score=item.vector_score,
                    vector_rank=item.vector_rank,
                    keyword_score=item.keyword_score,
                    keyword_rank=item.keyword_rank,
                )
                for item in response.items
            ],
        )
    except Exception as exc:
        logger.error("Search debug query failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {exc}",
        )

