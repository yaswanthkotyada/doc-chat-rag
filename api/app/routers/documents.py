import asyncio
import logging
import math
from pathlib import Path
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.conversation import Conversation
from app.models.document import Document, DocumentPage
from app.schemas.document import (
    DocumentPageDetail,
    DocumentPagesListResponse,
    DocumentPageSummary,
    DocumentParseResponse,
    DocumentParseSummary,
    DocumentRead,
)
from app.services.ingestion import ingest_document, parse_document_task
from app.services.storage import (
    FileTooLargeError,
    OfficeFileNotSupportedError,
    StorageError,
    UnsupportedFileTypeError,
    delete_document_files,
    get_document_file_path,
    get_document_parsed_md_path,
    sanitize_filename,
    save_upload_stream,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])


@router.post("/conversations/{conversation_id}/documents", response_model=List[DocumentRead], status_code=status.HTTP_201_CREATED)
async def upload_documents(
    conversation_id: uuid.UUID,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db)
):
    # 1. Verify conversation exists
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalar_one_or_none()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    # 2. Check batch file count limits
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided for upload."
        )

    if len(files) > settings.MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot upload more than {settings.MAX_FILES_PER_REQUEST} files per request."
        )

    # 3. Check conversation total files limit
    count_stmt = select(func.count(Document.id)).where(Document.conversation_id == conversation_id)
    current_count = await db.scalar(count_stmt) or 0
    if current_count + len(files) > settings.MAX_FILES_PER_CONVERSATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conversation cannot exceed {settings.MAX_FILES_PER_CONVERSATION} documents (currently has {current_count})."
        )

    created_docs: List[Document] = []

    # 4. Process each file independently so one bad file doesn't fail the whole batch
    for file in files:
        clean_filename = sanitize_filename(file.filename or "file")
        doc_id = uuid.uuid4()

        try:
            saved_path, size_bytes, sha256_hash, mime_type = await save_upload_stream(file, doc_id)
            doc = Document(
                id=doc_id,
                conversation_id=conversation_id,
                filename=clean_filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=sha256_hash,
                status="processing",
                error=None,
                meta={}
            )
            db.add(doc)
            created_docs.append(doc)

        except (OfficeFileNotSupportedError, UnsupportedFileTypeError, FileTooLargeError) as err:
            logger.warning("Validation error on file %s: %s", clean_filename, err)
            doc = Document(
                id=doc_id,
                conversation_id=conversation_id,
                filename=clean_filename,
                mime_type="application/octet-stream",
                size_bytes=0,
                sha256="",
                status="failed",
                error=str(err),
                meta={}
            )
            db.add(doc)
            created_docs.append(doc)

        except Exception as err:
            logger.error("Unexpected error saving file %s: %s", clean_filename, err, exc_info=False)
            doc = Document(
                id=doc_id,
                conversation_id=conversation_id,
                filename=clean_filename,
                mime_type="application/octet-stream",
                size_bytes=0,
                sha256="",
                status="failed",
                error="Failed to process uploaded file",
                meta={}
            )
            db.add(doc)
            created_docs.append(doc)

    await db.commit()
    for doc in created_docs:
        await db.refresh(doc)
        if doc.status == "processing":
            asyncio.create_task(ingest_document(doc.id))

    return created_docs


@router.get("/conversations/{conversation_id}/documents", response_model=List[DocumentRead])
async def list_conversation_documents(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    # Verify conversation exists
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    if not conv_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    stmt = (
        select(Document)
        .where(Document.conversation_id == conversation_id)
        .order_by(Document.created_at.asc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.id == document_id)
    res = await db.execute(stmt)
    document = res.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.id == document_id)
    res = await db.execute(stmt)
    document = res.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    file_path = get_document_file_path(document.id, document.mime_type)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File content not found on server"
        )

    # Inline disposition for images and PDFs, attachment otherwise
    is_inline = document.mime_type.startswith("image/") or document.mime_type == "application/pdf"
    disposition = "inline" if is_inline else "attachment"

    return FileResponse(
        path=str(file_path),
        media_type=document.mime_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'{disposition}; filename="{document.filename}"',
        }
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Document).where(Document.id == document_id)
    res = await db.execute(stmt)
    document = res.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    await db.delete(document)
    await db.commit()

    # Physically delete document files from disk
    delete_document_files(document.id)
    return None


@router.get("/documents/{document_id}/parse", response_model=DocumentParseResponse)
async def get_document_parse_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get parse status, progress, timing, and warnings summary for a document."""
    stmt = select(Document).where(Document.id == document_id)
    res = await db.execute(stmt)
    document = res.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Compute duration
    duration = None
    if document.parse_started_at and document.parse_finished_at:
        duration = round((document.parse_finished_at - document.parse_started_at).total_seconds(), 2)

    # Query pages to compute warnings summary
    p_stmt = select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_no.asc())
    p_res = await db.execute(p_stmt)
    pages = p_res.scalars().all()

    warnings_summary = None
    if pages:
        low_text = [p.page_no for p in pages if "low_text" in (p.warnings or [])]
        garbled = [p.page_no for p in pages if "garbled" in (p.warnings or [])]
        tbl_count = sum(1 for p in pages if p.has_table)
        fig_count = sum(1 for p in pages if p.has_figure)
        total_chars = sum(p.char_count for p in pages)
        total_warn = sum(len(p.warnings or []) for p in pages)

        warnings_summary = DocumentParseSummary(
            total_warnings=total_warn,
            low_text_pages=low_text,
            garbled_pages=garbled,
            pages_with_tables=tbl_count,
            pages_with_figures=fig_count,
            total_characters=total_chars,
        )

    return DocumentParseResponse(
        document_id=document.id,
        parse_status=document.parse_status,
        parse_error=document.parse_error,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        parse_started_at=document.parse_started_at,
        parse_finished_at=document.parse_finished_at,
        duration_seconds=duration,
        pages_parsed=document.pages_parsed or 0,
        total_pages=document.page_count,
        parse_options=document.parse_options,
        warnings_summary=warnings_summary,
    )


@router.post("/documents/{document_id}/parse/retry", response_model=DocumentParseResponse)
async def retry_document_parse(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Re-run parsing for a document (clears previous pages first)."""
    stmt = select(Document).where(Document.id == document_id)
    res = await db.execute(stmt)
    document = res.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.mime_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF documents can be parsed",
        )

    if document.parse_status == "parsing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parsing is already in progress for this document",
        )

    # Clear previous pages from DB
    await db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))

    # Reset parse fields
    document.parse_status = "pending"
    document.parse_error = None
    document.pages_parsed = 0
    if document.mode == "rag":
        document.status = "processing"
        document.error = None

    await db.commit()
    await db.refresh(document)

    # Schedule background parse task
    asyncio.create_task(parse_document_task(document.id))

    return DocumentParseResponse(
        document_id=document.id,
        parse_status=document.parse_status,
        parse_error=document.parse_error,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        parse_started_at=document.parse_started_at,
        parse_finished_at=document.parse_finished_at,
        duration_seconds=None,
        pages_parsed=0,
        total_pages=document.page_count,
        parse_options=document.parse_options,
        warnings_summary=None,
    )


@router.get("/documents/{document_id}/pages", response_model=DocumentPagesListResponse)
async def list_document_pages(
    document_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """List paginated pages for a parsed document."""
    # Verify document exists
    doc_stmt = select(Document.id).where(Document.id == document_id)
    doc_res = await db.execute(doc_stmt)
    if not doc_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    count_stmt = select(func.count(DocumentPage.id)).where(DocumentPage.document_id == document_id)
    total_count = await db.scalar(count_stmt) or 0

    offset = (page - 1) * limit
    p_stmt = (
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_no.asc())
        .offset(offset)
        .limit(limit)
    )
    p_res = await db.execute(p_stmt)
    page_records = p_res.scalars().all()

    total_pages = math.ceil(total_count / limit) if total_count > 0 else 0

    return DocumentPagesListResponse(
        items=[DocumentPageSummary.model_validate(p) for p in page_records],
        total=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/documents/{document_id}/pages/{page_no}", response_model=DocumentPageDetail)
async def get_document_page_detail(
    document_id: uuid.UUID,
    page_no: int,
    db: AsyncSession = Depends(get_db),
):
    """Get single page details (Markdown + plain text) for a parsed document."""
    p_stmt = select(DocumentPage).where(
        DocumentPage.document_id == document_id,
        DocumentPage.page_no == page_no,
    )
    p_res = await db.execute(p_stmt)
    page_obj = p_res.scalar_one_or_none()
    if not page_obj:
        # Check if document exists
        doc_stmt = select(Document.id).where(Document.id == document_id)
        doc_res = await db.execute(doc_stmt)
        if not doc_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_no} not found for document",
        )

    return DocumentPageDetail.model_validate(page_obj)


@router.get("/documents/{document_id}/parsed.md")
async def download_parsed_markdown(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Download full assembled Markdown file as an attachment."""
    stmt = select(Document).where(Document.id == document_id)
    res = await db.execute(stmt)
    document = res.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    md_path = get_document_parsed_md_path(document_id)
    if not md_path.exists():
        if document.parse_status != "parsed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Document has not been parsed yet (current status: {document.parse_status or 'pending'})",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parsed markdown file not found on server",
        )

    base_name = Path(document.filename).stem or "document"
    download_filename = f"{base_name}.parsed.md"

    return FileResponse(
        path=str(md_path),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"',
        },
    )

