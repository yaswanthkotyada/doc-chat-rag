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
from app.prompts import DEFAULT_SYSTEM_PROMPT, GROUNDED_SYSTEM_PROMPT, RAG_AGENT_SYSTEM_PROMPT
from app.schemas.chat import ChatRequest
from app.services.chat_agent import run_agent_loop
from app.services.citations import parse_and_validate_citations
from app.services.llm import LLMConfigurationError, LLMError, LLMRateLimitError, LLMSafetyError, llm_service
from app.services.router import route_documents
from app.services.tools.handlers import ToolExecutionContext

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

    # 2. Resolve selected documents
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
        # Default: all ready direct documents or indexed rag documents
        doc_stmt = (
            select(Document)
            .where(
                Document.conversation_id == conversation.id,
                (
                    (Document.mode == "direct") & (Document.status == "ready")
                ) | (
                    (Document.mode == "rag") & (Document.index_status == "indexed")
                )
            )
        )
        doc_result = await db.execute(doc_stmt)
        selected_docs = list(doc_result.scalars().all())

    # 3. Route documents through pure router
    routing_plan = route_documents(selected_docs)

    # 4. Determine user message content
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

    # 5. Save user message to database
    user_meta = None
    if selected_docs:
        user_meta = {
            "attached_documents": [
                {
                    "id": str(d.id),
                    "filename": d.filename,
                    "mime_type": d.mime_type,
                    "size_bytes": d.size_bytes,
                    "page_count": d.page_count,
                    "mode": d.mode,
                    "mode_override": getattr(d, "mode_override", None),
                }
                for d in selected_docs
            ],
            "routing_plan": routing_plan.to_dict(),
        }

    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=user_content,
        meta=user_meta
    )
    db.add(user_message)

    # Auto-title if this is the first exchange
    if not conversation.title:
        conversation.title = user_content[:60].strip()

    conversation.updated_at = func.now()
    await db.commit()

    # If documents were attached but ALL were excluded, report exclusion cleanly
    if selected_docs and routing_plan.mode == "none":
        exclusion_lines = ["None of the selected document(s) could be used:"]
        for exc in routing_plan.excluded_documents:
            exclusion_lines.append(f"- **{exc.filename}**: {exc.reason}")
        exclusion_msg = "\n".join(exclusion_lines)

        async def excluded_generator() -> AsyncGenerator[str, None]:
            yield format_sse("plan", routing_plan.to_dict())
            yield format_sse("token", exclusion_msg)
            async with async_session_factory() as save_db:
                assistant_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=exclusion_msg,
                    meta={"routing_plan": routing_plan.to_dict()}
                )
                save_db.add(assistant_msg)
                await save_db.commit()
                await save_db.refresh(assistant_msg)
                asst_id = str(assistant_msg.id)
            yield format_sse("done", {"message_id": asst_id, "usage": None})

        return StreamingResponse(
            excluded_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

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

    # 7. Execute chat streaming (RAG Mode vs Direct Mode vs Default Chat)
    async def event_generator() -> AsyncGenerator[str, None]:
        accumulated_chunks: List[str] = []
        is_completed = False
        usage_collector: Dict[str, Any] = {}

        # Emit routing plan first
        yield format_sse("plan", routing_plan.to_dict())

        try:
            # -------------------------------------------------------------
            # Branch A: RAG Mode or Mixed Mode (Agent Loop with Tool Calling)
            # -------------------------------------------------------------
            if routing_plan.mode in ("rag", "mixed"):
                # Direct-mode document parts (for mixed mode)
                direct_parts: Optional[List[Any]] = None
                if routing_plan.direct_documents:
                    direct_parts = await llm_service.build_document_parts(routing_plan.direct_documents, db)

                # Tool Execution Context scoped strictly to allowed RAG documents
                allowed_rag_ids = [d.id for d in routing_plan.rag_documents]
                tool_ctx = ToolExecutionContext(
                    db=db,
                    conversation_id=conversation_id,
                    allowed_document_ids=allowed_rag_ids,
                )

                loop_stream = run_agent_loop(
                    system_instruction=RAG_AGENT_SYSTEM_PROMPT,
                    messages=formatted_history,
                    tool_context=tool_ctx,
                    attached_parts=direct_parts,
                    attached_doc_names=[d.filename for d in routing_plan.direct_documents] if routing_plan.direct_documents else None,
                    is_cancelled=lambda: False,
                )

                loop_final_result = None

                async for event_type, payload in loop_stream:
                    if await request.is_disconnected():
                        logger.info("Client disconnected during RAG agent loop for conversation %s", conversation_id)
                        break

                    if event_type == "tool_call":
                        yield format_sse("tool_call", payload)

                    elif event_type == "tool_result":
                        yield format_sse("tool_result", payload)

                    elif event_type == "token":
                        accumulated_chunks.append(payload)
                        yield format_sse("token", payload)

                    elif event_type == "done":
                        loop_final_result = payload

                if loop_final_result:
                    raw_content = loop_final_result.content
                    # Resolve result IDs (R1, R2) to canonical document citations
                    cleaned_content, citations = parse_and_validate_citations(
                        raw_content,
                        selected_docs,
                        result_registry=loop_final_result.registry
                    )

                    meta_payload: Dict[str, Any] = {
                        "agent_trace": loop_final_result.agent_trace,
                        "routing_plan": routing_plan.to_dict(),
                        "limit_hit": loop_final_result.limit_hit,
                        "total_steps": loop_final_result.total_steps,
                        "total_tool_calls": loop_final_result.total_tool_calls,
                    }
                    if citations:
                        meta_payload["citations"] = citations
                    if loop_final_result.usage:
                        meta_payload["usage"] = loop_final_result.usage

                    # Save full assistant message
                    async with async_session_factory() as save_db:
                        assistant_msg = Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=cleaned_content,
                            meta=meta_payload
                        )
                        save_db.add(assistant_msg)
                        await save_db.commit()
                        await save_db.refresh(assistant_msg)
                        assistant_msg_id = str(assistant_msg.id)

                    is_completed = True
                    yield format_sse("done", {
                        "message_id": assistant_msg_id,
                        "citations": citations,
                        "usage": loop_final_result.usage or None,
                        "agent_trace": loop_final_result.agent_trace,
                        "routing_plan": routing_plan.to_dict(),
                        "limit_hit": loop_final_result.limit_hit,
                    })

            # -------------------------------------------------------------
            # Branch B: Direct Mode or General Assistant (Standard Streaming)
            # -------------------------------------------------------------
            else:
                if routing_plan.direct_documents:
                    system_instruction = GROUNDED_SYSTEM_PROMPT
                    attached_parts = await llm_service.build_document_parts(routing_plan.direct_documents, db)
                else:
                    system_instruction = DEFAULT_SYSTEM_PROMPT
                    attached_parts = None

                stream = llm_service.stream_chat(
                    system_instruction=system_instruction,
                    messages=formatted_history,
                    attached_parts=attached_parts,
                    attached_doc_names=[d.filename for d in routing_plan.direct_documents] if routing_plan.direct_documents else None,
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
                    cleaned_content, citations = parse_and_validate_citations(full_content, routing_plan.direct_documents)

                    async with async_session_factory() as save_db:
                        meta_payload: Dict[str, Any] = {
                            "routing_plan": routing_plan.to_dict(),
                        }
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
                        "usage": usage_collector or None,
                        "routing_plan": routing_plan.to_dict(),
                    })

        except asyncio.CancelledError:
            logger.info("Chat stream task cancelled for conversation %s", conversation_id)
        except (LLMConfigurationError, LLMRateLimitError, LLMSafetyError, LLMError) as e:
            logger.warning("LLM error during stream: %s", e)
            yield format_sse("error", str(e))
        except Exception as e:
            logger.error("Unhandled error in chat event generator: %s", e, exc_info=True)
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
