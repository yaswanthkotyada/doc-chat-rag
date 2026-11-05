import logging
import uuid
from typing import List
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.conversation import Conversation
from app.models.document import Document
from app.schemas.document import DocumentRead
from app.services.storage import (
    FileTooLargeError,
    OfficeFileNotSupportedError,
    StorageError,
    UnsupportedFileTypeError,
    delete_document_files,
    get_document_file_path,
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
