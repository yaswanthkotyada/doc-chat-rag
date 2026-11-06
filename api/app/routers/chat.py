import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory, get_db
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.prompts import DEFAULT_SYSTEM_PROMPT, GROUNDED_SYSTEM_PROMPT
from app.schemas.chat import ChatRequest
from app.services.citations import parse_and_validate_citations
from app.services.llm import LLMConfigurationError, LLMError, LLMRateLimitError, LLMSafetyError, llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def format_sse(event: str, data: Any) -> str:
    """Format SSE event string safely."""
    if isinstance(data, (dict, list)):
        payload = json.dumps(data)
    else:
        payload = json.dumps({"text": str(data)})
    return f"event: {event}\ndata: {payload}\n\n"


async def _save_interrupted_message(conversation_id: uuid.UUID, content: str) -> None:
    async with async_session_factory() as save_db:
        partial_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            meta={"interrupted": True}
        )
        save_db.add(partial_msg)
        await save_db.commit()


@router.post("/chat")
async def chat_endpoint(
    request: Request,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    # 1. Verify conversation exists
    conv_stmt = select(Conversation).where(Conversation.id == payload.conversation_id)
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    # 2. Resolve attached documents
    selected_docs: List[Document] = []
    if payload.document_ids is not None:
        if payload.document_ids:
            doc_stmt = (
                select(Document)
                .where(
                    Document.id.in_(payload.document_ids),
                    Document.conversation_id == conversation.id,
                )
            )
            doc_result = await db.execute(doc_stmt)
            selected_docs = list(doc_result.scalars().all())
    else:
        # Default: all ready documents with mode == 'direct'
        doc_stmt = (
            select(Document)
            .where(
                Document.conversation_id == conversation.id,
                Document.status == "ready",
                Document.mode == "direct",
            )
        )
        doc_result = await db.execute(doc_stmt)
        selected_docs = list(doc_result.scalars().all())

    # Check if any selected document has mode 'rag'
    rag_docs = [d for d in selected_docs if d.mode == "rag"]
    if rag_docs:
        rag_warning = "This document is too large for direct mode. Large-document support arrives in a later stage."

        # Save user message first
        user_content = payload.message.strip() or "Describe this file."
        user_msg = Message(
            conversation_id=conversation.id,
            role="user",
            content=user_content
        )
        db.add(user_msg)
        if not conversation.title:
            conversation.title = user_content[:60].strip()
        conversation.updated_at = func.now()
        await db.commit()

        async def rag_warning_generator() -> AsyncGenerator[str, None]:
            yield format_sse("token", rag_warning)
            async with async_session_factory() as save_db:
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=rag_warning,
                    meta=None
                )
                save_db.add(assistant_msg)
                await save_db.commit()
                await save_db.refresh(assistant_msg)
                assistant_msg_id = str(assistant_msg.id)
            yield format_sse("done", {"message_id": assistant_msg_id, "usage": None})

        return StreamingResponse(
            rag_warning_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    # 3. Determine user message content (default prompt if empty and files attached)
    trimmed_message = payload.message.strip()
    if not trimmed_message:
        if selected_docs:
            user_content = "Describe this file."
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message cannot be empty when no documents are attached."
            )
    else:
        user_content = trimmed_message

    # 4. Save user message to database
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=user_content
    )
    db.add(user_message)

    # 5. Auto-title if this is the first exchange
    if not conversation.title:
        conversation.title = user_content[:60].strip()

    conversation.updated_at = func.now()
    await db.commit()

    # 6. Fetch conversation history up to HISTORY_MAX_MESSAGES
    hist_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    )
    hist_result = await db.execute(hist_stmt)
    all_messages = hist_result.scalars().all()

    recent_messages = all_messages[-settings.HISTORY_MAX_MESSAGES:]
    formatted_history: List[Dict[str, str]] = [
        {"role": m.role, "content": m.content}
        for m in recent_messages
    ]

    conversation_id = conversation.id

    # 7. Select appropriate system instruction and build document parts
    if selected_docs:
        system_instruction = GROUNDED_SYSTEM_PROMPT
        attached_parts = await llm_service.build_document_parts(selected_docs, db)
    else:
        system_instruction = DEFAULT_SYSTEM_PROMPT
        attached_parts = None

    async def event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks: List[str] = []
        is_completed = False
        usage_collector: Dict[str, Any] = {}

        try:
            stream = llm_service.stream_chat(
                system_instruction=system_instruction,
                messages=formatted_history,
                attached_parts=attached_parts,
                attached_doc_names=[d.filename for d in selected_docs] if selected_docs else None,
                usage_collector=usage_collector,
            )

            async for chunk in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected during stream for conversation %s", conversation_id)
                    break

                accumulated_chunks.append(chunk)
                yield format_sse("token", chunk)

            full_content = "".join(accumulated_chunks)
            if full_content:
                # Parse and validate citations against conversation documents
                cleaned_content, citations = parse_and_validate_citations(full_content, selected_docs)

                # Save full assistant message
                async with async_session_factory() as save_db:
                    meta_payload: Dict[str, Any] = {}
                    if citations:
                        meta_payload["citations"] = citations
                    if usage_collector:
                        meta_payload["usage"] = usage_collector

                    assistant_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=cleaned_content,
                        meta=meta_payload if meta_payload else None
                    )
                    save_db.add(assistant_msg)
                    await save_db.commit()
                    await save_db.refresh(assistant_msg)
                    assistant_msg_id = str(assistant_msg.id)

                is_completed = True
                yield format_sse("done", {
                    "message_id": assistant_msg_id,
                    "citations": citations,
                    "usage": usage_collector or None
                })

        except asyncio.CancelledError:
            logger.info("Chat stream task cancelled for conversation %s", conversation_id)
        except (LLMConfigurationError, LLMRateLimitError, LLMSafetyError, LLMError) as e:
            logger.warning("LLM error during stream: %s", e)
            yield format_sse("error", str(e))
        except Exception as e:
            logger.error("Unhandled error in chat event generator: %s", e, exc_info=False)
            yield format_sse("error", "An error occurred while generating the response.")
        finally:
            if not is_completed and accumulated_chunks:
                partial_content = "".join(accumulated_chunks)
                try:
                    await asyncio.shield(_save_interrupted_message(conversation_id, partial_content))
                    logger.info("Saved interrupted message for conversation %s", conversation_id)
                except Exception as save_err:
                    logger.error("Failed to save interrupted message: %s", save_err)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
