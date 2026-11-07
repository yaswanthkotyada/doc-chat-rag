"""
Stage 7 - Gemini Tool Execution Handlers: services/tools/handlers.py

Executes search_documents, read_surrounding, and list_documents against the database.
Enforces conversation document scoping security, generates sequential result IDs (R1, R2...),
handles query deduplication, result trimming, and maps citations back to chunks.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Chunk, Document
from app.services.search import search_chunks

logger = logging.getLogger(__name__)


@dataclass
class ToolRegistryItem:
    result_id: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_filename: str
    chunk_index: int
    page_start: int
    page_end: int
    heading_path: List[str]
    chunk_type: str
    token_count: int
    text: str


def _trim_text(text: str, max_chars: int) -> str:
    """Trim chunk text to max_chars without cutting mid-word if possible."""
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    last_space = trimmed.rfind(" ")
    if last_space > max_chars * 0.8:
        trimmed = trimmed[:last_space]
    return trimmed.rstrip() + " ... [truncated]"


class ToolExecutionContext:
    """
    Per-turn execution context for Gemini tool calls.
    Maintains result ID mapping (R1, R2...), caches searches, and enforces document isolation.
    """

    def __init__(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        allowed_document_ids: List[uuid.UUID],
    ):
        self.db = db
        self.conversation_id = conversation_id
        self.allowed_document_ids = list(allowed_document_ids)
        self.registry: Dict[str, ToolRegistryItem] = {}
        self.search_cache: Dict[str, Dict[str, Any]] = {}
        self._next_id_counter = 1

    def _allocate_result_id(self) -> str:
        res_id = f"R{self._next_id_counter}"
        self._next_id_counter += 1
        return res_id

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call safely, returning a clean dictionary for Part.from_function_response."""
        try:
            if tool_name == "search_documents":
                query = str(args.get("query", "")).strip()
                top_k = args.get("top_k", 5)
                return await self.search_documents(query=query, top_k=top_k)

            elif tool_name == "read_surrounding":
                result_id = str(args.get("result_id", "")).strip()
                before = int(args.get("before", 1))
                after = int(args.get("after", 1))
                return await self.read_surrounding(result_id=result_id, before=before, after=after)

            elif tool_name == "list_documents":
                return await self.list_documents()

            else:
                return {"error": f"Unknown tool '{tool_name}'."}

        except Exception as e:
            logger.error("Error executing tool %s: %s", tool_name, str(e), exc_info=False)
            return {"error": "A transient error occurred while searching documents. Please retry or rephrase."}

    async def search_documents(self, query: str, top_k: Optional[int] = 5) -> Dict[str, Any]:
        """Execute hybrid search restricted to allowed conversation documents."""
        if not query:
            return {"error": "Search query cannot be empty."}

        if not self.allowed_document_ids:
            return {"results": [], "total_found": 0, "note": "No indexed documents are available for this conversation."}

        # Deduplication check
        cache_key = f"{query.lower()}||{top_k}"
        if cache_key in self.search_cache:
            cached = dict(self.search_cache[cache_key])
            cached["note"] = f"Identical query previously returned {cached.get('total_found', 0)} results. (Showing cached passages)."
            return cached

        # Cap top_k to configured limit
        limit = min(max(int(top_k or 5), 1), settings.SEARCH_MAX_TOP_K)

        # Execute hybrid search
        search_res = await search_chunks(
            db=self.db,
            query=query,
            mode="hybrid",
            limit=limit,
            document_ids=self.allowed_document_ids,
            conversation_id=self.conversation_id,
        )

        formatted_items = []
        for item in search_res.items:
            # Check if this chunk is already registered
            existing_id = None
            for r_id, reg in self.registry.items():
                if reg.chunk_id == item.chunk_id:
                    existing_id = r_id
                    break

            result_id = existing_id or self._allocate_result_id()

            if not existing_id:
                self.registry[result_id] = ToolRegistryItem(
                    result_id=result_id,
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    document_filename=item.document_filename,
                    chunk_index=item.chunk_index,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    heading_path=item.heading_path,
                    chunk_type=item.chunk_type,
                    token_count=item.token_count,
                    text=item.text,
                )

            page_label = f"p.{item.page_start}" if item.page_start == item.page_end else f"p.{item.page_start}-{item.page_end}"
            heading_str = " > ".join(item.heading_path) if item.heading_path else ""

            formatted_items.append({
                "result_id": result_id,
                "filename": item.document_filename,
                "pages": page_label,
                "heading": heading_str,
                "chunk_type": item.chunk_type,
                "text": _trim_text(item.text, settings.SEARCH_RESULT_MAX_CHARS),
            })

        output = {
            "results": formatted_items,
            "total_found": len(formatted_items),
            "note": "For each claim based on these results, cite [cite: R#] directly after the statement.",
        }

        self.search_cache[cache_key] = output
        return output

    async def read_surrounding(
        self,
        result_id: str,
        before: int = 1,
        after: int = 1,
    ) -> Dict[str, Any]:
        """Read adjacent chunks before and after a previously retrieved result."""
        clean_id = result_id.upper().strip()
        reg_item = self.registry.get(clean_id)

        if not reg_item:
            return {
                "error": f"Result ID '{result_id}' was not found in prior searches. Use search_documents first."
            }

        # Cap surrounding range: 0 to 2
        before_count = max(0, min(before, 2))
        after_count = max(0, min(after, 2))

        if before_count == 0 and after_count == 0:
            return {"results": [], "note": "No surrounding range requested (before=0, after=0)."}

        target_indices = []
        for offset in range(-before_count, after_count + 1):
            if offset != 0:
                target_indices.append(reg_item.chunk_index + offset)

        stmt = (
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.chunk_index,
                Chunk.text,
                Chunk.page_start,
                Chunk.page_end,
                Chunk.heading_path,
                Chunk.chunk_type,
                Chunk.token_count,
                Document.filename.label("document_filename"),
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Chunk.document_id == reg_item.document_id,
                Chunk.chunk_index.in_(target_indices),
                Chunk.document_id.in_(self.allowed_document_ids),
            )
            .order_by(Chunk.chunk_index.asc())
        )

        rows = (await self.db.execute(stmt)).mappings().all()

        formatted_items = []
        for row in rows:
            # Check existing registry
            existing_id = None
            for r_id, reg in self.registry.items():
                if reg.chunk_id == row["id"]:
                    existing_id = r_id
                    break

            res_id = existing_id or self._allocate_result_id()

            if not existing_id:
                self.registry[res_id] = ToolRegistryItem(
                    result_id=res_id,
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    document_filename=row["document_filename"],
                    chunk_index=row["chunk_index"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    heading_path=row["heading_path"] or [],
                    chunk_type=row["chunk_type"],
                    token_count=row["token_count"],
                    text=row["text"],
                )

            p_start, p_end = row["page_start"], row["page_end"]
            page_label = f"p.{p_start}" if p_start == p_end else f"p.{p_start}-{p_end}"
            heading_str = " > ".join(row["heading_path"]) if row["heading_path"] else ""
            rel = "preceding" if row["chunk_index"] < reg_item.chunk_index else "succeeding"

            formatted_items.append({
                "result_id": res_id,
                "relationship": f"{rel} chunk relative to {clean_id}",
                "filename": row["document_filename"],
                "pages": page_label,
                "heading": heading_str,
                "chunk_type": row["chunk_type"],
                "text": _trim_text(row["text"], settings.SEARCH_RESULT_MAX_CHARS),
            })

        return {
            "surrounding_results": formatted_items,
            "total_found": len(formatted_items),
            "note": f"Retrieved {len(formatted_items)} neighboring chunk(s) for {clean_id}.",
        }

    async def list_documents(self) -> Dict[str, Any]:
        """Return filenames and metadata of available RAG documents for this conversation."""
        if not self.allowed_document_ids:
            return {"documents": [], "total_documents": 0}

        stmt = (
            select(
                Document.id,
                Document.filename,
                Document.page_count,
                Document.chunks_count,
                Document.size_bytes,
            )
            .where(
                Document.id.in_(self.allowed_document_ids),
                Document.conversation_id == self.conversation_id,
            )
            .order_by(Document.filename.asc())
        )

        rows = (await self.db.execute(stmt)).mappings().all()

        docs_info = [
            {
                "document_id": str(r["id"]),
                "filename": r["filename"],
                "pages": r["page_count"],
                "chunks": r["chunks_count"],
                "size_mb": round(r["size_bytes"] / (1024 * 1024), 2),
            }
            for r in rows
        ]

        return {
            "documents": docs_info,
            "total_documents": len(docs_info),
        }
