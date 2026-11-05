import logging
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response, db: AsyncSession = Depends(get_db)):
    api_status = "ok"
    db_status = "ok"
    pgvector_status = "ok"

    # 1. Check DB connection
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("DB health check failed: %s", e)
        db_status = "error"

    # 2. Check pgvector extension
    if db_status == "ok":
        try:
            result = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            if result.scalar_one_or_none() is None:
                pgvector_status = "missing"
        except Exception as e:
            logger.error("pgvector check failed: %s", e)
            pgvector_status = "missing"
    else:
        pgvector_status = "missing"

    # 3. Check Gemini API key configuration
    gemini_key_configured = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())

    # 4. Set HTTP status code (200 if db and pgvector are ok, otherwise 503)
    if db_status == "ok" and pgvector_status == "ok":
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        api=api_status,
        db=db_status,
        pgvector=pgvector_status,
        gemini_key_configured=gemini_key_configured,
    )

