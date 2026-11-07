"""
Milestone 2 Verification Script: test_agent_real.py

Runs the manual agent loop against the real indexed document ('RFP SMART COPS.pdf')
without the UI, printing the full multi-step tool execution trace and final output.
"""

import asyncio
import json
import uuid
from app.db import async_session_factory
from app.prompts import RAG_AGENT_SYSTEM_PROMPT
from app.services.chat_agent import run_agent_loop
from app.services.tools.handlers import ToolExecutionContext

DOC_ID = uuid.UUID("47ee5f5f-c5dd-4859-81e7-18364dd1e5ce")
CONV_ID = uuid.UUID("52557fdf-b87b-46ae-9527-f0936d695f7c")


async def main():
    print("=" * 80)
    print("STAGE 7 - MILESTONE 2: REAL DOCUMENT AGENT LOOP TEST")
    print(f"Document ID: {DOC_ID}")
    print(f"Conversation ID: {CONV_ID}")
    print("=" * 80)

    question = "What are the camera specifications and technical requirements required under this RFP?"
    print(f"\nUser Query: {question}\n")

    async with async_session_factory() as db:
        tool_ctx = ToolExecutionContext(
            db=db,
            conversation_id=CONV_ID,
            allowed_document_ids=[DOC_ID],
        )

        messages = [{"role": "user", "content": question}]

        print("--- STARTING AGENT LOOP ---")
        async for event_type, payload in run_agent_loop(
            system_instruction=RAG_AGENT_SYSTEM_PROMPT,
            messages=messages,
            tool_context=tool_ctx,
        ):
            if event_type == "tool_call":
                print(f"\n>>> [TOOL CALL - Step {payload['step']}]")
                print(f"    Tool:      {payload['tool']}")
                print(f"    Arguments: {json.dumps(payload['arguments'])}")

            elif event_type == "tool_result":
                print(f"\n<<< [TOOL RESULT - Step {payload['step']}]")
                print(f"    Tool:      {payload['tool']}")
                print(f"    Found:     {payload['result_count']} passages")
                print(f"    Pages:     {payload['pages']}")
                print(f"    Duration:  {payload['duration_ms']} ms")
                print("--- STREAMING MODEL RESPONSE ---")

            elif event_type == "token":
                # Print token directly
                print(payload, end="", flush=True)

            elif event_type == "done":
                print("\n\n" + "=" * 80)
                print("AGENT EXECUTION TRACE SUMMARY:")
                print(f"Total Steps:      {payload.total_steps}")
                print(f"Total Tool Calls: {payload.total_tool_calls}")
                print(f"Limit Hit:        {payload.limit_hit}")
                print(f"Usage:            {json.dumps(payload.usage)}")
                print(f"Registry Items:   {len(payload.registry)}")
                for r_id, reg in payload.registry.items():
                    print(f"  [{r_id}] -> {reg.document_filename} (p.{reg.page_start}-{reg.page_end}) chunk={reg.chunk_index}")
                print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

