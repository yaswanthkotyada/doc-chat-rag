"""
Stage 7 - Multi-Step RAG Agent Loop: services/chat_agent.py

Implements a manual function-calling agent loop with Gemini streaming:
- Manual control over tool execution (automatic_function_calling disabled)
- Enforces AGENT_MAX_STEPS, AGENT_MAX_TOOL_CALLS, and AGENT_MAX_RETRIEVED_TOKENS
- Forces final text answer (FunctionCallingConfigMode.NONE) upon hitting limits
- Streams per-step SSE events: 'tool_call', 'tool_result', 'token', 'done', 'error'
- Concurrent execution of parallel function calls via asyncio.gather
- Maintains complete agent trace without leaking chunk text or keys into logs
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config import settings
from app.services.llm import (
    LLMConfigurationError,
    LLMError,
    LLMRateLimitError,
    LLMSafetyError,
    _sanitize_message,
    llm_service,
)
from app.services.tools.definitions import get_rag_tools
from app.services.tools.handlers import ToolExecutionContext, ToolRegistryItem

logger = logging.getLogger(__name__)


@dataclass
class AgentStepTrace:
    step: int
    tool: str
    arguments: Dict[str, Any]
    result_count: int
    pages: List[int]
    chunk_ids: List[str]
    duration_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "arguments": self.arguments,
            "result_count": self.result_count,
            "pages": self.pages,
            "chunk_ids": self.chunk_ids,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentLoopResult:
    content: str
    agent_trace: List[Dict[str, Any]]
    limit_hit: bool
    total_steps: int
    total_tool_calls: int
    registry: Dict[str, ToolRegistryItem]
    usage: Dict[str, Any]


def _extract_pages_and_ids(tool_res: Dict[str, Any], registry: Dict[str, ToolRegistryItem]) -> Tuple[List[int], List[str]]:
    """Extract distinct sorted page numbers and chunk UUIDs from tool execution output."""
    pages_set = set()
    chunk_ids = []

    results = tool_res.get("results") or tool_res.get("surrounding_results") or []
    for item in results:
        res_id = item.get("result_id")
        if res_id and res_id in registry:
            reg = registry[res_id]
            chunk_ids.append(str(reg.chunk_id))
            for p in range(reg.page_start, reg.page_end + 1):
                pages_set.add(p)

    return sorted(list(pages_set)), chunk_ids


async def run_agent_loop(
    system_instruction: str,
    messages: List[Dict[str, str]],
    tool_context: ToolExecutionContext,
    attached_parts: Optional[List[types.Part]] = None,
    attached_doc_names: Optional[List[str]] = None,
    model: Optional[str] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> AsyncGenerator[Tuple[str, Any], None]:
    """
    Execute the manual multi-step tool-calling agent loop.
    Yields tuple of (event_type, event_payload):
      ('tool_call', {step, tool, args})
      ('tool_result', {step, tool, count, pages, duration_ms})
      ('token', text_chunk)
      ('done', AgentLoopResult)
      ('error', error_str)
    """
    model_name = model or settings.GEMINI_MODEL
    client = llm_service._get_client()

    # 1. Build initial multi-turn contents
    contents: List[types.Content] = []
    for i, msg in enumerate(messages):
        role = "model" if msg.get("role") in ("assistant", "model") else "user"
        content_text = msg.get("content", "")
        is_latest_user_turn = (i == len(messages) - 1) and (role == "user")

        parts: List[types.Part] = []

        # Attach direct-mode document parts strictly to the latest user message
        if is_latest_user_turn and attached_parts:
            parts.extend(attached_parts)

        if is_latest_user_turn and not content_text and attached_parts:
            content_text = "Describe this file."

        if content_text:
            parts.append(types.Part.from_text(text=content_text))

        if parts:
            contents.append(types.Content(role=role, parts=parts))

    if not contents:
        raise LLMError("Cannot run agent loop with empty messages.")

    agent_traces: List[AgentStepTrace] = []
    accumulated_content_chunks: List[str] = []
    usage_collector: Dict[str, Any] = {}

    total_tool_calls = 0
    step_num = 0
    limit_hit = False
    rag_tools = get_rag_tools()

    loop_start_time = time.monotonic()

    # 2. Manual Agent Step Loop
    while step_num < settings.AGENT_MAX_STEPS:
        if is_cancelled and is_cancelled():
            logger.info("Agent loop cancelled by client.")
            break

        # Check total timeout
        if time.monotonic() - loop_start_time > settings.AGENT_TIMEOUT_SECONDS:
            logger.warning("Agent loop reached AGENT_TIMEOUT_SECONDS (%s s). Forcing final answer.", settings.AGENT_TIMEOUT_SECONDS)
            limit_hit = True

        # Check tool call cap or step cap
        force_final = limit_hit or (total_tool_calls >= settings.AGENT_MAX_TOOL_CALLS) or (step_num >= settings.AGENT_MAX_STEPS - 1)
        if (total_tool_calls >= settings.AGENT_MAX_TOOL_CALLS or step_num >= settings.AGENT_MAX_STEPS - 1) and not force_final:
            limit_hit = True
            force_final = True

        mode = (
            types.FunctionCallingConfigMode.NONE
            if force_final
            else types.FunctionCallingConfigMode.AUTO
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            tools=rag_tools,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=mode)
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        step_num += 1
        model_parts_this_turn: List[types.Part] = []
        function_calls_this_turn = []
        text_received_this_turn = False

        try:
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=config,
            )

            async for chunk in stream:
                if is_cancelled and is_cancelled():
                    break

                # Collect usage
                if chunk.usage_metadata:
                    usage_collector["prompt_tokens"] = chunk.usage_metadata.prompt_token_count
                    usage_collector["candidates_tokens"] = chunk.usage_metadata.candidates_token_count
                    usage_collector["total_tokens"] = chunk.usage_metadata.total_token_count

                # Safety checks
                if chunk.candidates:
                    for cand in chunk.candidates:
                        if cand.finish_reason:
                            reason = str(cand.finish_reason).upper()
                            if "SAFETY" in reason:
                                raise LLMSafetyError("Response was interrupted due to content safety policies.")
                            elif "RECITATION" in reason:
                                raise LLMSafetyError("Response was interrupted due to recitation policy.")

                        # Collect raw parts to preserve cryptographic thought_signatures
                        if cand.content and cand.content.parts:
                            model_parts_this_turn.extend(cand.content.parts)

                # Check for function calls
                if chunk.function_calls:
                    function_calls_this_turn.extend(chunk.function_calls)

                # Stream text if not a tool call
                if chunk.text and not chunk.function_calls:
                    text_received_this_turn = True
                    accumulated_content_chunks.append(chunk.text)
                    yield ("token", chunk.text)

        except APIError as e:
            err_msg = _sanitize_message(str(e.message if hasattr(e, "message") else e))
            code = getattr(e, "code", None)
            logger.error("Gemini API error during agent step %d: %s", step_num, err_msg)
            if code == 429:
                raise LLMRateLimitError("Gemini rate limit exceeded. Please try again shortly.") from e
            elif code == 400:
                raise LLMConfigurationError(f"Invalid request to AI service: {err_msg}") from e
            else:
                raise LLMError(f"AI service error: {err_msg}") from e

        # Case A: Model requested tool execution(s)
        if function_calls_this_turn and not force_final:
            total_tool_calls += len(function_calls_this_turn)

            # Record model's function call turn into multi-turn contents
            contents.append(types.Content(role="model", parts=model_parts_this_turn))

            # Emit 'tool_call' events for each call
            for fc in function_calls_this_turn:
                yield ("tool_call", {
                    "step": step_num,
                    "tool": fc.name,
                    "arguments": dict(fc.args or {}),
                })

            # Concurrently execute parallel tool calls
            t0 = time.monotonic()
            tasks = [
                tool_context.execute(fc.name, dict(fc.args or {}))
                for fc in function_calls_this_turn
            ]
            results = await asyncio.gather(*tasks)
            duration_ms = round((time.monotonic() - t0) * 1000, 2)

            # Build user response turn with types.Part.from_function_response
            response_parts: List[types.Part] = []
            for fc, res in zip(function_calls_this_turn, results):
                response_parts.append(
                    types.Part.from_function_response(name=fc.name, response=res)
                )

                pages, chunk_ids = _extract_pages_and_ids(res, tool_context.registry)
                count = res.get("total_found", len(res.get("results", [])))

                step_trace = AgentStepTrace(
                    step=step_num,
                    tool=fc.name,
                    arguments=dict(fc.args or {}),
                    result_count=count,
                    pages=pages,
                    chunk_ids=chunk_ids,
                    duration_ms=duration_ms,
                )
                agent_traces.append(step_trace)

                yield ("tool_result", {
                    "step": step_num,
                    "tool": fc.name,
                    "result_count": count,
                    "pages": pages,
                    "duration_ms": duration_ms,
                })

            contents.append(types.Content(role="user", parts=response_parts))

            # If force_final is now triggered, inject reminder to synthesize answer from retrieved context
            if total_tool_calls >= settings.AGENT_MAX_TOOL_CALLS or step_num >= settings.AGENT_MAX_STEPS - 1:
                limit_hit = True
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text="[System Note: Maximum tool search limit reached. Please provide a complete final answer now using the passages retrieved above, clearly stating what could or could not be verified.]"
                            )
                        ]
                    )
                )

            # Continue to next iteration of agent loop to get answer or next step
            continue

        # Case B: Model returned text answer (or completed after force_final)
        if text_received_this_turn or accumulated_content_chunks:
            break

        # Edge case: Model returned neither tool call nor text
        if not function_calls_this_turn and not text_received_this_turn:
            logger.warning("Model returned empty turn on step %d. Forcing final answer.", step_num)
            force_final = True
            limit_hit = True

    # 3. Final Result Compilation
    final_text = "".join(accumulated_content_chunks)
    result = AgentLoopResult(
        content=final_text,
        agent_trace=[t.to_dict() for t in agent_traces],
        limit_hit=limit_hit,
        total_steps=step_num,
        total_tool_calls=total_tool_calls,
        registry=dict(tool_context.registry),
        usage=usage_collector,
    )

    yield ("done", result)
