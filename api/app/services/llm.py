import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.services.storage import get_document_file_path

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM service errors."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when LLM configuration/key is missing or invalid."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when rate limits are exceeded."""
    pass


class LLMSafetyError(LLMError):
    """Raised when safety or policy blocks are triggered."""
    pass


def _sanitize_message(message: str) -> str:
    """Ensure the API key and internal file URIs are never leaked in error messages or logs."""
    import re
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY in message:
        message = message.replace(settings.GEMINI_API_KEY, "[REDACTED]")
    # Redact internal Gemini files URI if present
    message = re.sub(r"https://generativelanguage\.googleapis\.com[^\s\'\"]+", "[REDACTED_URI]", message)
    return message


class GeminiLLMService:
    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.default_model = default_model or settings.GEMINI_MODEL
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if not self.api_key:
            raise LLMConfigurationError("Gemini API key is not configured. Please set GEMINI_API_KEY.")
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def ensure_gemini_file(
        self,
        document: Document,
        db: AsyncSession
    ) -> types.Part:
        """
        Ensure document is uploaded to the Gemini Files API and return a File Part.
        Uses cached Gemini file URI if still valid (> 5 min before 48h expiry);
        otherwise transparently uploads from local disk and polls until ACTIVE.
        """
        client = self._get_client()
        meta = dict(document.meta or {})
        gemini_file_name = meta.get("gemini_file_name")
        gemini_file_uri = meta.get("gemini_file_uri")
        gemini_file_expires_at = meta.get("gemini_file_expires_at")

        # 1. Check if cached file is still valid
        is_valid = False
        if gemini_file_name and gemini_file_uri and gemini_file_expires_at:
            try:
                exp_dt = datetime.fromisoformat(gemini_file_expires_at)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                # Keep if at least 5 minutes remaining before expiration
                if datetime.now(timezone.utc) + timedelta(minutes=5) < exp_dt:
                    is_valid = True
            except Exception:
                is_valid = False

        if is_valid:
            logger.debug("Using cached Gemini file URI for document %s", document.id)
            return types.Part.from_uri(file_uri=gemini_file_uri, mime_type=document.mime_type)

        # 2. File missing or expired; upload from disk
        file_path = get_document_file_path(document.id, document.mime_type)
        if not file_path.exists():
            raise LLMError(f"File for document '{document.filename}' was not found on server disk.")

        logger.info("Uploading document %s (%s) to Gemini Files API...", document.id, document.filename)
        try:
            uploaded_file = await client.aio.files.upload(
                file=str(file_path),
                config=types.UploadFileConfig(
                    mime_type=document.mime_type,
                    display_name=document.filename,
                )
            )

            # Poll until ACTIVE with timeout
            start_time = time.monotonic()
            timeout = settings.GEMINI_FILE_UPLOAD_TIMEOUT_SECONDS
            while True:
                state_name = uploaded_file.state.name if uploaded_file.state else ""
                if state_name == "ACTIVE":
                    break
                if state_name == "FAILED":
                    raise LLMError("Gemini file processing failed on the server.")
                if time.monotonic() - start_time > timeout:
                    raise LLMError("Gemini file upload timed out while processing.")
                await asyncio.sleep(1.0)
                uploaded_file = await client.aio.files.get(name=uploaded_file.name)

            # Store in document meta
            expires_at = uploaded_file.expiration_time
            expires_at_str = expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)
            meta.update({
                "gemini_file_name": uploaded_file.name,
                "gemini_file_uri": uploaded_file.uri,
                "gemini_file_expires_at": expires_at_str,
            })
            document.meta = meta
            await db.commit()
            logger.info("Document %s uploaded to Gemini Files API successfully: state=ACTIVE", document.id)

            return types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=document.mime_type)

        except APIError as e:
            err_msg = _sanitize_message(str(e.message if hasattr(e, "message") else e))
            logger.error("APIError uploading file %s to Gemini: %s", document.id, err_msg)
            raise LLMError(f"Failed to upload document to AI service: {err_msg}") from e
        except Exception as e:
            if isinstance(e, LLMError):
                raise
            err_msg = _sanitize_message(str(e))
            logger.error("Error uploading file %s to Gemini: %s", document.id, err_msg)
            raise LLMError("An error occurred while uploading document to AI service.") from e

    async def build_document_parts(
        self,
        documents: List[Document],
        db: AsyncSession
    ) -> List[types.Part]:
        """
        Build multimodal Parts for documents attached to the current turn:
        - PDF: header text label + Part.from_uri (via Files API)
        - Images: header text label + Part.from_bytes (inline)
        - Text / Markdown: header text label + full content Part.from_text
        - CSV: header text label + truncated rows Part.from_text (respecting CSV_MAX_ROWS_DIRECT)
        """
        parts: List[types.Part] = []

        for doc in documents:
            if doc.mime_type == "application/pdf":
                pages_desc = f"{doc.page_count} pages" if doc.page_count else "PDF"
                label = f"Document: {doc.filename} ({pages_desc})"
                parts.append(types.Part.from_text(text=label))
                pdf_part = await self.ensure_gemini_file(doc, db)
                parts.append(pdf_part)

            elif doc.mime_type.startswith("image/"):
                dims = f" ({doc.width}x{doc.height})" if doc.width and doc.height else ""
                label = f"Image: {doc.filename}{dims}"
                parts.append(types.Part.from_text(text=label))
                file_path = get_document_file_path(doc.id, doc.mime_type)
                if not file_path.exists():
                    raise LLMError(f"File for image '{doc.filename}' not found on server disk.")
                img_bytes = file_path.read_bytes()
                parts.append(types.Part.from_bytes(data=img_bytes, mime_type=doc.mime_type))

            elif doc.mime_type in ("text/plain", "text/markdown"):
                file_path = get_document_file_path(doc.id, doc.mime_type)
                if not file_path.exists():
                    raise LLMError(f"File for document '{doc.filename}' not found on server disk.")
                raw_text = file_path.read_text(encoding="utf-8", errors="replace")
                formatted = f"Document: {doc.filename}\n---\n{raw_text}\n---"
                parts.append(types.Part.from_text(text=formatted))

            elif doc.mime_type == "text/csv":
                file_path = get_document_file_path(doc.id, doc.mime_type)
                if not file_path.exists():
                    raise LLMError(f"File for CSV '{doc.filename}' not found on server disk.")
                raw_text = file_path.read_text(encoding="utf-8", errors="replace")
                lines = raw_text.splitlines(keepends=True)
                if len(lines) > settings.CSV_MAX_ROWS_DIRECT:
                    truncated = "".join(lines[: settings.CSV_MAX_ROWS_DIRECT])
                    note = f"\n[Note: Truncated to first {settings.CSV_MAX_ROWS_DIRECT} of {len(lines)} rows for direct mode.]"
                    formatted = f"Document: {doc.filename} (CSV, showing first {settings.CSV_MAX_ROWS_DIRECT} of {len(lines)} rows)\n---\n{truncated}{note}\n---"
                else:
                    formatted = f"Document: {doc.filename} (CSV, {len(lines)} rows)\n---\n{raw_text}\n---"
                parts.append(types.Part.from_text(text=formatted))

        return parts

    async def count_tokens(
        self,
        contents: List[types.Content],
        model: Optional[str] = None
    ) -> int:
        """Count total tokens for a multimodal request."""
        client = self._get_client()
        model_name = model or self.default_model
        try:
            res = await client.aio.models.count_tokens(model=model_name, contents=contents)
            return res.total_tokens
        except APIError as e:
            err_msg = _sanitize_message(str(e.message if hasattr(e, "message") else e))
            logger.error("APIError during count_tokens: %s", err_msg)
            raise LLMError(f"Failed to calculate token count: {err_msg}") from e
        except Exception as e:
            err_msg = _sanitize_message(str(e))
            logger.error("Error during count_tokens: %s", err_msg)
            raise LLMError("An error occurred while calculating token count.") from e

    async def stream_chat(
        self,
        system_instruction: str,
        messages: List[Dict[str, str]],
        attached_parts: Optional[List[types.Part]] = None,
        attached_doc_names: Optional[List[str]] = None,
        usage_collector: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream text response from Gemini given conversation history and optional attached document parts.
        - `attached_parts` are attached strictly to the latest user message.
        - `attached_doc_names` are document filenames used for clear error messages.
        - `usage_collector` is a dict populated with token usage statistics upon completion.
        """
        model_name = model or self.default_model

        try:
            client = self._get_client()
        except LLMConfigurationError as e:
            raise e

        # Construct multi-turn contents for Gemini SDK
        contents: List[types.Content] = []
        for i, msg in enumerate(messages):
            role = "model" if msg.get("role") in ("assistant", "model") else "user"
            content_text = msg.get("content", "")
            is_latest_user_turn = (i == len(messages) - 1) and (role == "user")

            parts: List[types.Part] = []

            # Attach document parts to the latest user message
            if is_latest_user_turn and attached_parts:
                parts.extend(attached_parts)

            # If user message is empty but has attached documents, default prompt is "Describe this file."
            if is_latest_user_turn and not content_text and attached_parts:
                content_text = "Describe this file."

            if content_text:
                parts.append(types.Part.from_text(text=content_text))

            if parts:
                contents.append(types.Content(role=role, parts=parts))

        if not contents:
            raise LLMError("Cannot call LLM with empty messages list.")

        # Check total token budget if direct mode limit is set
        total_tokens = await self.count_tokens(contents=contents, model=model_name)
        if total_tokens > settings.DIRECT_MAX_TOTAL_TOKENS:
            doc_str = f" with attached documents ({', '.join(attached_doc_names)})" if attached_doc_names else ""
            raise LLMError(
                f"Combined request{doc_str} exceeds token limit ({total_tokens:,} tokens > {settings.DIRECT_MAX_TOTAL_TOKENS:,} max). "
                "Please deselect one or more documents."
            )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
        )

        try:
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=config,
            )

            async for chunk in stream:
                # Collect usage metadata from final chunks
                if chunk.usage_metadata and usage_collector is not None:
                    usage_collector["prompt_tokens"] = chunk.usage_metadata.prompt_token_count
                    usage_collector["candidates_tokens"] = chunk.usage_metadata.candidates_token_count
                    usage_collector["total_tokens"] = chunk.usage_metadata.total_token_count

                # Check for finish reasons like safety blocks mid-stream
                if chunk.candidates:
                    for candidate in chunk.candidates:
                        if candidate.finish_reason:
                            reason = str(candidate.finish_reason).upper()
                            if "SAFETY" in reason:
                                raise LLMSafetyError("Response was interrupted due to content safety policies.")
                            elif "RECITATION" in reason:
                                raise LLMSafetyError("Response was interrupted due to recitation policy.")

                if chunk.text:
                    yield chunk.text

        except APIError as e:
            err_msg = _sanitize_message(str(e.message if hasattr(e, "message") else e))
            code = getattr(e, "code", None)
            logger.error("Gemini APIError encountered: code=%s, message=%s", code, err_msg)

            if code == 400:
                raise LLMConfigurationError("Invalid Gemini request or invalid API key.") from e
            elif code == 429:
                raise LLMRateLimitError("Gemini rate limit exceeded. Please try again shortly.") from e
            else:
                raise LLMError(f"Gemini API returned error: {err_msg}") from e

        except (LLMError, LLMSafetyError, LLMRateLimitError, LLMConfigurationError):
            raise

        except Exception as e:
            err_msg = _sanitize_message(str(e))
            logger.error("Unexpected error in GeminiLLMService: %s", err_msg)
            raise LLMError("An unexpected error occurred while communicating with the AI service.") from e


# Singleton service instance
llm_service = GeminiLLMService()
