import asyncio
from datetime import datetime, timezone
import logging
import uuid
from typing import Optional
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import delete, select, update

from app.config import settings
from app.db import async_session_factory
from app.models.document import Chunk, Document, DocumentPage
from app.services.chunking import chunk_document
from app.services.embeddings import get_embedding_service
from app.services.parsers import (
    DoclingClientParser,
    DocumentParserError,
    ParsedDocument,
    ParserUnavailableError,
)
from app.services.storage import (
    get_document_file_path,
    get_document_parsed_json_path,
    save_parsed_artifacts,
)

logger = logging.getLogger(__name__)

# Semaphore to bound concurrent parsing tasks
_parse_semaphore = asyncio.Semaphore(settings.PARSE_CONCURRENCY)


def should_parse_document(mime_type: str, mode: Optional[str]) -> bool:
    """Check if document qualifies for parsing based on PARSE_MODE and file type."""
    if settings.PARSE_MODE == "off":
        return False
    if mime_type != "application/pdf":
        return False
    if settings.PARSE_MODE == "rag_only":
        return mode == "rag"
    if settings.PARSE_MODE == "all_pdfs":
        return True
    return False


async def parse_document_task(document_id: uuid.UUID) -> None:
    """
    Background worker that parses a document with Docling.
    Throttled by PARSE_CONCURRENCY semaphore.
    Idempotent: clears partial/previous pages before storing new ones.
    """
    logger.info("Queued parse task for document %s (waiting for parser slot)...", document_id)

    async with _parse_semaphore:
        logger.info("Starting parse task execution for document %s", document_id)
        now = datetime.now(timezone.utc)
        enqueue_index = False

        # 1. Initialize parsing state in DB
        async with async_session_factory() as db:
            stmt = select(Document).where(Document.id == document_id)
            result = await db.execute(stmt)
            document = result.scalar_one_or_none()

            if not document:
                logger.warning("Parse aborted: document %s not found in DB", document_id)
                return

            file_path = get_document_file_path(document.id, document.mime_type)
            if not file_path.exists():
                document.parse_status = "failed"
                document.parse_error = "Document file missing on disk"
                if document.mode == "rag":
                    document.status = "failed"
                    document.error = "Document file missing on disk"
                await db.commit()
                return

            # Clear any previously stored pages for this document (idempotent retry)
            await db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))

            document.parse_status = "parsing"
            document.parse_error = None
            document.parse_started_at = now
            document.parse_finished_at = None
            document.pages_parsed = 0
            if document.mode == "rag":
                document.status = "processing"

            await db.commit()

        # 2. Execute parsing with Docling
        parser = DoclingClientParser(base_url=settings.DOCLING_URL)

        def on_batch_progress(pages_done: int, total_pages: int):
            async def _update_progress():
                try:
                    async with async_session_factory() as prog_db:
                        await prog_db.execute(
                            update(Document)
                            .where(Document.id == document_id)
                            .values(pages_parsed=pages_done)
                        )
                        await prog_db.commit()
                except Exception as pe:
                    logger.warning("Failed to record parse progress for %s: %s", document_id, pe)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_update_progress())
            except Exception as e:
                logger.warning("Could not schedule progress update: %s", e)

        try:
            parsed_doc: ParsedDocument = await parser.parse(
                file_path=file_path,
                options={
                    "batch_pages": settings.PARSE_BATCH_PAGES,
                    "do_ocr": settings.PARSE_OCR_ENABLED,
                    "timeout_seconds": settings.PARSE_TIMEOUT_SECONDS,
                    "min_chars_per_page": settings.PARSE_MIN_CHARS_PER_PAGE,
                    "on_progress": on_batch_progress,
                },
            )

            # 3. Save raw JSON and full markdown artifacts to disk
            save_parsed_artifacts(
                document_id=document_id,
                raw_json=parsed_doc.raw_json,
                full_markdown=parsed_doc.full_markdown,
            )

            # 4. Save per-page records and update document state in DB
            finished_at = datetime.now(timezone.utc)
            async with async_session_factory() as db:
                stmt = select(Document).where(Document.id == document_id)
                result = await db.execute(stmt)
                document = result.scalar_one_or_none()
                if not document:
                    return

                # Insert page records
                for page in parsed_doc.pages:
                    db_page = DocumentPage(
                        document_id=document.id,
                        page_no=page.page_no,
                        markdown=page.markdown,
                        plain_text=page.plain_text,
                        char_count=page.char_count,
                        has_table=page.has_table,
                        has_figure=page.has_figure,
                        ocr_used=page.ocr_used,
                        warnings=page.warnings,
                    )
                    db.add(db_page)

                document.parse_status = "parsed"
                document.parse_error = None
                document.parser_name = parsed_doc.parser_name
                document.parser_version = parsed_doc.parser_version
                document.pages_parsed = parsed_doc.page_count
                document.parse_finished_at = finished_at
                document.parse_options = {
                    "batch_pages": settings.PARSE_BATCH_PAGES,
                    "do_ocr": settings.PARSE_OCR_ENABLED,
                }

                # Update page_count if not set previously
                if not document.page_count:
                    document.page_count = parsed_doc.page_count

                # RAG documents become 'ready' only after parsing completes
                if document.mode == "rag":
                    document.status = "ready"
                    document.error = None
                    document.index_status = "pending"
                    enqueue_index = True
                else:
                    document.index_status = "skipped"

                await db.commit()

            logger.info(
                "Document %s parsed successfully: %d pages stored",
                document_id,
                parsed_doc.page_count,
            )

            if enqueue_index:
                asyncio.create_task(index_document_task(document_id))

        except ParserUnavailableError as pue:
            logger.warning("Docling service unavailable during parsing for %s: %s", document_id, pue)
            safe_error = "Parsing service unavailable"
            async with async_session_factory() as db:
                stmt = select(Document).where(Document.id == document_id)
                result = await db.execute(stmt)
                doc = result.scalar_one_or_none()
                if doc:
                    doc.parse_status = "failed"
                    doc.parse_error = safe_error
                    doc.parse_finished_at = datetime.now(timezone.utc)
                    if doc.mode == "rag":
                        doc.status = "failed"
                        doc.error = safe_error
                    await db.commit()

        except Exception as err:
            logger.error("Document parsing failed for %s: %s", document_id, err, exc_info=False)
            err_str = str(err).lower()
            if "timed out" in err_str:
                safe_error = "Parsing request timed out"
            else:
                safe_error = f"Document parsing failed: {err}"[:200]

            async with async_session_factory() as db:
                stmt = select(Document).where(Document.id == document_id)
                result = await db.execute(stmt)
                doc = result.scalar_one_or_none()
                if doc:
                    doc.parse_status = "failed"
                    doc.parse_error = safe_error
                    doc.parse_finished_at = datetime.now(timezone.utc)
                    if doc.mode == "rag":
                        doc.status = "failed"
                        doc.error = safe_error
                    await db.commit()


async def index_document_task(document_id: uuid.UUID) -> None:
    """
    Background worker that chunks, embeds, and indexes a parsed document.
    Idempotent: clears any existing chunks for this document before inserting new ones.
    """
    logger.info("Queued index task for document %s...", document_id)
    doc_filename = ""

    # 1. Update index_status to 'indexing'
    async with async_session_factory() as db:
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        document = result.scalar_one_or_none()

        if not document:
            logger.warning("Index task aborted: document %s not found in DB", document_id)
            return

        if document.parse_status != "parsed":
            logger.warning(
                "Document %s is not parsed yet (parse_status=%s). Skipping index.",
                document_id, document.parse_status
            )
            return

        document.index_status = "indexing"
        document.index_error = None
        doc_filename = document.filename
        await db.commit()

    try:
        # 2. Read parsed docling.json if present, or fallback to DocumentPage rows
        raw_json = None
        json_path = get_document_parsed_json_path(document_id)
        if json_path.exists():
            try:
                import json
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_json = json.load(f)
            except Exception as j_err:
                logger.warning("Could not read docling.json for %s: %s; falling back to DB pages", document_id, j_err)

        pages_data = None
        if not raw_json:
            async with async_session_factory() as db:
                p_stmt = (
                    select(DocumentPage)
                    .where(DocumentPage.document_id == document_id)
                    .order_by(DocumentPage.page_no.asc())
                )
                p_res = await db.execute(p_stmt)
                pages_data = [
                    {"page_no": p.page_no, "markdown": p.markdown}
                    for p in p_res.scalars().all()
                ]

        # 3. Chunk document using services/chunking.py
        chunks = chunk_document(
            doc_name=doc_filename,
            raw_json=raw_json,
            pages=pages_data,
            target_tokens=settings.CHUNK_TARGET_TOKENS,
            max_tokens=settings.CHUNK_MAX_TOKENS,
            overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
            min_tokens=settings.CHUNK_MIN_TOKENS,
        )

        logger.info("Document %s chunked into %d chunk(s)", document_id, len(chunks))

        # 4. Generate embeddings using services/embeddings.py
        embeddings = []
        if chunks:
            embed_texts = [c.embed_text for c in chunks]
            embedding_service = get_embedding_service()
            embeddings = await embedding_service.embed_chunks(embed_texts, task_type="RETRIEVAL_DOCUMENT")

        # 5. Persist chunks and update document state atomically
        finished_at = datetime.now(timezone.utc)
        async with async_session_factory() as db:
            # Delete previous chunks if any (idempotent retry)
            await db.execute(delete(Chunk).where(Chunk.document_id == document_id))

            # Insert new chunks
            for c, emb in zip(chunks, embeddings):
                db_chunk = Chunk(
                    document_id=document_id,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    embed_text=c.embed_text,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    heading_path=c.heading_path,
                    chunk_type=c.chunk_type,
                    token_count=c.token_count,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    embedding=emb,
                )
                db.add(db_chunk)

            # Update Document record
            doc_stmt = select(Document).where(Document.id == document_id)
            doc_res = await db.execute(doc_stmt)
            doc = doc_res.scalar_one_or_none()
            if doc:
                doc.index_status = "indexed"
                doc.index_error = None
                doc.chunks_count = len(chunks)
                doc.indexed_at = finished_at
                doc.status = "ready"
                doc.error = None

            await db.commit()

        logger.info(
            "Document %s indexed successfully with %d chunks (status=ready, index_status=indexed)",
            document_id, len(chunks)
        )

    except Exception as exc:
        logger.error("Indexing failed for document %s: %s", document_id, exc, exc_info=False)
        safe_err = f"Document indexing failed: {exc}"[:250]
        async with async_session_factory() as db:
            doc_stmt = select(Document).where(Document.id == document_id)
            doc_res = await db.execute(doc_stmt)
            doc = doc_res.scalar_one_or_none()
            if doc:
                doc.index_status = "failed"
                doc.index_error = safe_err
            await db.commit()


async def ingest_document(document_id: uuid.UUID) -> None:
    """
    Background ingestion task: inspects document file on disk, extracts
    metadata (page_count, width/height, lines/characters), assigns mode,
    and dispatches parsing if qualified.
    """
    logger.info("Starting ingestion for document: %s", document_id)

    # Optional artificial delay for observing status transitions
    if settings.INGEST_FAKE_DELAY_SECONDS > 0:
        await asyncio.sleep(settings.INGEST_FAKE_DELAY_SECONDS)

    enqueue_parse = False

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
            document.parse_status = "skipped"
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
                except PyPdfError:
                    document.status = "failed"
                    document.error = "Corrupted or invalid PDF file"
                except Exception:
                    document.status = "failed"
                    document.error = "Failed to process PDF document"

            # 2. Image Inspection
            elif document.mime_type.startswith("image/"):
                try:
                    with Image.open(str(file_path)) as img:
                        width, height = img.size
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

            # 4. Mode assignment (Stage 4: Direct vs RAG)
            if document.status == "ready":
                max_direct_bytes = settings.DIRECT_MAX_MB * 1024 * 1024
                if document.mime_type == "application/pdf":
                    if (
                        document.page_count is not None
                        and document.page_count <= settings.DIRECT_MAX_PAGES
                        and document.size_bytes <= max_direct_bytes
                    ):
                        document.mode = "direct"
                    else:
                        document.mode = "rag"
                elif document.mime_type.startswith("image/"):
                    if document.size_bytes <= max_direct_bytes:
                        document.mode = "direct"
                    else:
                        document.mode = "rag"
                elif document.mime_type in ("text/plain", "text/markdown", "text/csv"):
                    if document.size_bytes <= max_direct_bytes:
                        document.mode = "direct"
                    else:
                        document.mode = "rag"
                else:
                    document.mode = "rag"
            else:
                document.mode = None

            # 5. Parsing & Indexing qualification (Stages 5 & 6)
            if document.status == "ready":
                if should_parse_document(document.mime_type, document.mode):
                    document.parse_status = "pending"
                    document.index_status = "pending" if document.mode == "rag" else "skipped"
                    enqueue_parse = True
                    # RAG mode documents remain in 'processing' status until parse finishes
                    if document.mode == "rag":
                        document.status = "processing"
                else:
                    document.parse_status = "skipped"
                    document.index_status = "skipped"
            else:
                document.parse_status = "skipped"
                document.index_status = "skipped"

        except Exception as unhandled:
            logger.error("Unhandled ingestion exception for %s: %s", document_id, unhandled, exc_info=False)
            document.status = "failed"
            document.error = "An error occurred during file ingestion"
            document.mode = None
            document.parse_status = "skipped"
            document.index_status = "skipped"

        await db.commit()
        logger.info(
            "Finished ingestion for document %s: status=%s, mode=%s, parse_status=%s",
            document_id,
            document.status,
            document.mode,
            document.parse_status,
        )

    # Launch background parse task if qualified
    if enqueue_parse:
        asyncio.create_task(parse_document_task(document_id))
