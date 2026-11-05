import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.db import async_session_factory
from app.models.document import Document
from app.routers.chat import router as chat_router
from app.routers.conversations import router as conversations_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.services.ingestion import ingest_document
from app.services.storage import get_document_file_path

logger = logging.getLogger(__name__)


async def run_startup_recovery():
    """Recover documents left in uploading or processing state during a restart."""
    logger.info("Checking for unfinished document ingestions across server restarts...")
    try:
        async with async_session_factory() as db:
            stmt = select(Document).where(Document.status.in_(["uploading", "processing"]))
            result = await db.execute(stmt)
            stuck_docs = result.scalars().all()

            for doc in stuck_docs:
                file_path = get_document_file_path(doc.id, doc.mime_type)
                if file_path.exists():
                    logger.info("Recovering document %s: file exists on disk, re-running ingestion", doc.id)
                    doc.status = "processing"
                    doc.error = None
                    asyncio.create_task(ingest_document(doc.id))
                else:
                    logger.warning("Failing document %s: file missing on disk after restart", doc.id)
                    doc.status = "failed"
                    doc.error = "Upload interrupted by server restart"

            await db.commit()
    except Exception as e:
        logger.error("Error during startup document recovery: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await run_startup_recovery()
    yield
    # Shutdown


app = FastAPI(title="DOC_POC API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(chat_router)


@app.get("/")
async def root():
    return {"message": "DOC_POC API is running"}
