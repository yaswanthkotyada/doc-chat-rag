import asyncio
import logging
import uuid
from typing import Optional
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import select

from app.config import settings
from app.db import async_session_factory
from app.models.document import Document
from app.services.storage import get_document_file_path

logger = logging.getLogger(__name__)


async def ingest_document(document_id: uuid.UUID) -> None:
    """
    Background ingestion task: inspects document file on disk, extracts
    metadata (page_count, width/height, lines/characters), and marks status ready or failed.
    """
    logger.info("Starting ingestion for document: %s", document_id)

    # Optional artificial delay for observing status transitions
    if settings.INGEST_FAKE_DELAY_SECONDS > 0:
        await asyncio.sleep(settings.INGEST_FAKE_DELAY_SECONDS)

    async with async_session_factory() as db:
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        document = result.scalar_one_or_none()

        if not document:
            logger.warning("Ingestion aborted: document %s not found in DB", document_id)
            return

        file_path = get_document_file_path(document.id, document.mime_type)
        if not file_path.exists():
            document.status = "failed"
            document.error = "Stored file is missing from server disk"
            await db.commit()
            return

        try:
            # 1. PDF Inspection
            if document.mime_type == "application/pdf":
                try:
                    reader = PdfReader(str(file_path))
                    if reader.is_encrypted:
                        document.status = "failed"
                        document.error = "Password-protected or encrypted PDFs are not supported"
                    else:
                        page_count = len(reader.pages)
                        if page_count <= 0:
                            document.status = "failed"
                            document.error = "PDF contains no readable pages"
                        else:
                            # Test reading the first page to catch stream/syntax corruption
                            _ = reader.pages[0]
                            document.page_count = page_count
                            document.status = "ready"
                            document.error = None
                except PyPdfError as pdf_err:
                    document.status = "failed"
                    document.error = "Corrupted or invalid PDF file"
                except Exception as e:
                    document.status = "failed"
                    document.error = "Failed to process PDF document"

            # 2. Image Inspection
            elif document.mime_type.startswith("image/"):
                try:
                    with Image.open(str(file_path)) as img:
                        width, height = img.size
                        # Verify integrity
                        img.verify()

                    document.width = width
                    document.height = height
                    document.status = "ready"
                    document.error = None
                except (UnidentifiedImageError, OSError):
                    document.status = "failed"
                    document.error = "Corrupted or invalid image file"
                except Exception:
                    document.status = "failed"
                    document.error = "Failed to process image file"

            # 3. Text / Markdown / CSV Inspection
            elif document.mime_type in ("text/plain", "text/markdown", "text/csv"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
                    characters = len(content)

                    current_meta = dict(document.meta or {})
                    current_meta.update({
                        "lines": lines,
                        "characters": characters
                    })
                    document.meta = current_meta
                    document.status = "ready"
                    document.error = None
                except UnicodeDecodeError:
                    document.status = "failed"
                    document.error = "Text file could not be decoded as UTF-8"
                except Exception:
                    document.status = "failed"
                    document.error = "Failed to inspect text file"

            else:
                document.status = "ready"
                document.error = None

        except Exception as unhandled:
            logger.error("Unhandled ingestion exception for %s: %s", document_id, unhandled, exc_info=False)
            document.status = "failed"
            document.error = "An error occurred during file ingestion"

        await db.commit()
        logger.info("Finished ingestion for document %s: status=%s", document_id, document.status)

