import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import List, Tuple
import filetype
from fastapi import UploadFile

from app.config import settings


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


class FileTooLargeError(StorageError):
    """Raised when an uploaded file exceeds the configured size limit."""
    pass


class UnsupportedFileTypeError(StorageError):
    """Raised when an uploaded file format is not allowed."""
    pass


class OfficeFileNotSupportedError(StorageError):
    """Raised when an Office document is uploaded."""
    pass


# Allowed MIME types and their canonical extensions
ALLOWED_BINARY_MIMES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}


def sanitize_filename(filename: str) -> str:
    """Sanitize the original filename for safe display and metadata storage."""
    if not filename:
        return "document"

    # Strip path separators and null characters
    name = os.path.basename(filename.replace("\\", "/"))
    # Remove control characters and problematic shell symbols
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '', name)
    name = name.strip(". ")

    if not name:
        return "document"

    # Limit length to 255 characters while preserving extension
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        allowed_stem_len = 255 - len(ext)
        name = f"{stem[:allowed_stem_len]}{ext}"

    return name


def detect_file_type(sample: bytes, original_filename: str) -> Tuple[str, str]:
    """
    Detect MIME type and extension from file header / magic bytes.
    Raises OfficeFileNotSupportedError or UnsupportedFileTypeError for disallowed types.
    """
    ext_lower = os.path.splitext(original_filename.lower())[1]

    # Check for Office files
    if ext_lower in OFFICE_EXTENSIONS or (sample.startswith(b"PK\x03\x04") and ext_lower in OFFICE_EXTENSIONS):
        raise OfficeFileNotSupportedError("Office files will be supported in a later stage")

    # Magic-byte check using pure-python filetype library
    kind = filetype.guess(sample)
    if kind is not None:
        mime = kind.mime
        if "officedocument" in mime or "msword" in mime or "ms-excel" in mime:
            raise OfficeFileNotSupportedError("Office files will be supported in a later stage")

        if mime in ALLOWED_BINARY_MIMES:
            return mime, ALLOWED_BINARY_MIMES[mime]

        raise UnsupportedFileTypeError(f"Unsupported file type: {mime}")

    # If filetype is None, test if it's UTF-8 encoded text
    if b"\x00" in sample:
        raise UnsupportedFileTypeError("Binary file format is not supported")

    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        raise UnsupportedFileTypeError("File could not be decoded as UTF-8 text")

    # Pure text mapping based on extension
    if ext_lower == ".csv":
        return "text/csv", ".csv"
    elif ext_lower in (".md", ".markdown"):
        return "text/markdown", ".md"
    elif ext_lower in (".txt", ""):
        return "text/plain", ".txt"

    raise UnsupportedFileTypeError(f"Unsupported text file format: {ext_lower}")


def get_document_dir(document_id: uuid.UUID) -> Path:
    """Get the physical storage directory for a given document."""
    upload_root = Path(settings.UPLOAD_DIR)
    return upload_root / str(document_id)


def get_document_file_path(document_id: uuid.UUID, mime_type: str) -> Path:
    """Get the exact file path for a stored document."""
    doc_dir = get_document_dir(document_id)
    ext = ALLOWED_BINARY_MIMES.get(mime_type, ".txt")
    if mime_type == "text/csv":
        ext = ".csv"
    elif mime_type == "text/markdown":
        ext = ".md"
    return doc_dir / f"original{ext}"


async def save_upload_stream(
    upload_file: UploadFile,
    document_id: uuid.UUID,
) -> Tuple[Path, int, str, str]:
    """
    Stream upload file to disk in chunks, computing SHA-256 and enforcing MAX_UPLOAD_MB.
    Returns (saved_path, size_bytes, sha256_hex, detected_mime).
    """
    doc_dir = get_document_dir(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)

    temp_path = doc_dir / "temp.upload"
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    hasher = hashlib.sha256()
    total_bytes = 0
    first_chunk = b""
    chunk_size = 64 * 1024  # 64 KB chunks

    try:
        with open(temp_path, "wb") as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break

                if not first_chunk:
                    first_chunk = chunk

                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise FileTooLargeError(
                        f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_MB} MB"
                    )

                hasher.update(chunk)
                f.write(chunk)

        if total_bytes == 0:
            raise UnsupportedFileTypeError("Uploaded file is empty (0 bytes)")

        # Validate file type using initial bytes
        detected_mime, canonical_ext = detect_file_type(first_chunk, upload_file.filename or "")

        # Atomically rename to final path
        final_path = doc_dir / f"original{canonical_ext}"
        if final_path.exists():
            final_path.unlink()
        temp_path.rename(final_path)

        return final_path, total_bytes, hasher.hexdigest(), detected_mime

    except Exception:
        # Clean up any partial files and folder on failure
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if doc_dir.exists():
            shutil.rmtree(doc_dir, ignore_errors=True)
        raise


def delete_document_files(document_id: uuid.UUID) -> None:
    """Delete all files and directory on disk for a given document."""
    doc_dir = get_document_dir(document_id)
    if doc_dir.exists():
        shutil.rmtree(doc_dir, ignore_errors=True)


def delete_conversation_files(document_ids: List[uuid.UUID]) -> None:
    """Delete files on disk for all documents in a deleted conversation."""
    for doc_id in document_ids:
        delete_document_files(doc_id)

