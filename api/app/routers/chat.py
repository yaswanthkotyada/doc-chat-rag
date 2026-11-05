import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory, get_db
from app.models.conversation import Conversation, Message
from app.prompts import DEFAULT_SYSTEM_PROMPT
from app.schemas.chat import ChatRequest
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

    # 2. Save user message to database
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.message
    )
    db.add(user_message)

    # 3. Auto-title if this is the first exchange
    if not conversation.title:
        # Truncate first message to ~60 chars
        conversation.title = payload.message[:60].strip()

    conversation.updated_at = func.now()
    await db.commit()

    # 4. Fetch conversation history up to HISTORY_MAX_MESSAGES
    hist_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    )
    hist_result = await db.execute(hist_stmt)
    all_messages = hist_result.scalars().all()

    # Slice the last N messages
    recent_messages = all_messages[-settings.HISTORY_MAX_MESSAGES:]
    formatted_history: List[Dict[str, str]] = [
        {"role": m.role, "content": m.content}
        for m in recent_messages
    ]

    conversation_id = conversation.id

    async def event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks: List[str] = []
        is_completed = False

        try:
            stream = llm_service.stream_chat(
                system_instruction=DEFAULT_SYSTEM_PROMPT,
                messages=formatted_history
            )

            async for chunk in stream:
                if await request.is_disconnected():
                    logger.info("Client disconnected during stream for conversation %s", conversation_id)
                    break

                accumulated_chunks.append(chunk)
                yield format_sse("token", chunk)

            full_content = "".join(accumulated_chunks)
            if full_content:
                # Save full assistant message
                async with async_session_factory() as save_db:
                    assistant_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_content,
                        meta=None
                    )
                    save_db.add(assistant_msg)
                    await save_db.commit()
                    await save_db.refresh(assistant_msg)
                    assistant_msg_id = str(assistant_msg.id)

                is_completed = True
                yield format_sse("done", {"message_id": assistant_msg_id, "usage": None})

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
                # Save partial interrupted message protected by shield against CancelledError
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
            "Content-Type": "text/event-stream",
            "X-Accel-Buffering": "no",
        }
    )

