"""
Unit tests for Stage 7 Tools: services/tools/definitions.py and handlers.py
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.config import settings
from app.models.document import Chunk, Document
from app.services.search import SearchResponse, SearchResultItem
from app.services.tools.definitions import (
    LIST_DOCUMENTS_DECLARATION,
    READ_SURROUNDING_DECLARATION,
    SEARCH_DOCUMENTS_DECLARATION,
    get_rag_tools,
)
from app.services.tools.handlers import ToolExecutionContext, ToolRegistryItem, _trim_text


def test_tool_declarations():
    tools = get_rag_tools()
    assert len(tools) == 1
    decls = tools[0].function_declarations
    assert len(decls) == 3

    decl_names = {d.name for d in decls}
    assert decl_names == {"search_documents", "read_surrounding", "list_documents"}

    # Validate search_documents parameters
    search_decl = next(d for d in decls if d.name == "search_documents")
    assert "query" in search_decl.parameters.properties
    assert search_decl.parameters.required == ["query"]

    # Validate read_surrounding parameters
    read_decl = next(d for d in decls if d.name == "read_surrounding")
    assert "result_id" in read_decl.parameters.properties
    assert read_decl.parameters.required == ["result_id"]


def test_trim_text():
    short_text = "This is a short text."
    assert _trim_text(short_text, 100) == short_text

    long_text = "Word " * 100  # 500 chars
    trimmed = _trim_text(long_text, 50)
    assert len(trimmed) <= 70
    assert trimmed.endswith("... [truncated]")


@pytest.mark.asyncio
async def test_search_documents_formatting_and_registry():
    conv_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk1_id = uuid.uuid4()
    chunk2_id = uuid.uuid4()

    mock_db = AsyncMock()
    ctx = ToolExecutionContext(db=mock_db, conversation_id=conv_id, allowed_document_ids=[doc_id])

    mock_search_res = SearchResponse(
        query="camera resolution",
        mode="hybrid",
        limit=5,
        total_results=2,
        duration_ms=45.0,
        items=[
            SearchResultItem(
                chunk_id=chunk1_id,
                document_id=doc_id,
                chunk_index=3,
                document_filename="manual.pdf",
                text="The camera supports 4K recording with HDR.",
                page_start=12,
                page_end=12,
                heading_path=["Specifications", "Camera"],
                chunk_type="text",
                token_count=50,
                score=0.85,
            ),
            SearchResultItem(
                chunk_id=chunk2_id,
                document_id=doc_id,
                chunk_index=4,
                document_filename="manual.pdf",
                text="Night vision capability operates up to 30 meters.",
                page_start=12,
                page_end=13,
                heading_path=["Specifications", "Night Vision"],
                chunk_type="text",
                token_count=45,
                score=0.72,
            ),
        ],
    )

    with patch("app.services.tools.handlers.search_chunks", new=AsyncMock(return_value=mock_search_res)):
        res = await ctx.execute("search_documents", {"query": "camera resolution", "top_k": 5})

    assert res["total_found"] == 2
    assert len(res["results"]) == 2

    # Check R1 and R2 assignment
    r1 = res["results"][0]
    r2 = res["results"][1]
    assert r1["result_id"] == "R1"
    assert r1["filename"] == "manual.pdf"
    assert r1["pages"] == "p.12"
    assert r1["heading"] == "Specifications > Camera"

    assert r2["result_id"] == "R2"
    assert r2["pages"] == "p.12-13"

    # Verify registry holds accurate items for citation resolution
    assert "R1" in ctx.registry
    assert ctx.registry["R1"].chunk_id == chunk1_id
    assert ctx.registry["R1"].page_start == 12
    assert ctx.registry["R1"].page_end == 12

    assert "R2" in ctx.registry
    assert ctx.registry["R2"].chunk_id == chunk2_id
    assert ctx.registry["R2"].page_start == 12
    assert ctx.registry["R2"].page_end == 13


@pytest.mark.asyncio
async def test_search_documents_deduplication():
    conv_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    ctx = ToolExecutionContext(db=AsyncMock(), conversation_id=conv_id, allowed_document_ids=[doc_id])

    mock_search_res = SearchResponse(
        query="penalty clause",
        mode="hybrid",
        limit=5,
        total_results=1,
        duration_ms=20.0,
        items=[
            SearchResultItem(
                chunk_id=uuid.uuid4(),
                document_id=doc_id,
                chunk_index=1,
                document_filename="contract.pdf",
                text="Penalty is 5% per week.",
                page_start=5,
                page_end=5,
                heading_path=[],
                chunk_type="text",
                token_count=20,
                score=0.9,
            )
        ],
    )

    with patch("app.services.tools.handlers.search_chunks", new=AsyncMock(return_value=mock_search_res)) as mock_exec:
        res1 = await ctx.execute("search_documents", {"query": "penalty clause"})
        assert mock_exec.call_count == 1

        # Second call with identical query should return cached result
        res2 = await ctx.execute("search_documents", {"query": "penalty clause"})
        assert mock_exec.call_count == 1
        assert "previously returned" in res2["note"]


@pytest.mark.asyncio
async def test_read_surrounding_invalid_id():
    conv_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    ctx = ToolExecutionContext(db=AsyncMock(), conversation_id=conv_id, allowed_document_ids=[doc_id])
    res = await ctx.execute("read_surrounding", {"result_id": "R99"})
    assert "error" in res
    assert "not found in prior searches" in res["error"]


@pytest.mark.asyncio
async def test_read_surrounding_valid():
    conv_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk1_id = uuid.uuid4()
    chunk2_id = uuid.uuid4()
    chunk3_id = uuid.uuid4()

    mock_db = AsyncMock()
    ctx = ToolExecutionContext(db=mock_db, conversation_id=conv_id, allowed_document_ids=[doc_id])

    # Pre-populate registry with R1 (chunk_index 5)
    ctx.registry["R1"] = ToolRegistryItem(
        result_id="R1",
        chunk_id=chunk2_id,
        document_id=doc_id,
        document_filename="spec.pdf",
        chunk_index=5,
        page_start=10,
        page_end=10,
        heading_path=["Section 3"],
        chunk_type="text",
        token_count=100,
        text="Middle chunk text",
    )

    # Mock DB query for chunk_index 4 and 6
    mock_db_result = MagicMock()
    mock_db_result.mappings.return_value.all.return_value = [
        {
            "id": chunk1_id,
            "document_id": doc_id,
            "chunk_index": 4,
            "text": "Preceding chunk text",
            "page_start": 9,
            "page_end": 10,
            "heading_path": ["Section 3"],
            "chunk_type": "text",
            "token_count": 90,
            "document_filename": "spec.pdf",
        },
        {
            "id": chunk3_id,
            "document_id": doc_id,
            "chunk_index": 6,
            "text": "Succeeding chunk text",
            "page_start": 10,
            "page_end": 11,
            "heading_path": ["Section 3"],
            "chunk_type": "text",
            "token_count": 95,
            "document_filename": "spec.pdf",
        },
    ]
    mock_db.execute = AsyncMock(return_value=mock_db_result)

    res = await ctx.execute("read_surrounding", {"result_id": "R1", "before": 1, "after": 1})

    assert res["total_found"] == 2
    assert len(res["surrounding_results"]) == 2
    assert "preceding" in res["surrounding_results"][0]["relationship"]
    assert "succeeding" in res["surrounding_results"][1]["relationship"]


@pytest.mark.asyncio
async def test_list_documents():
    conv_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    mock_db = AsyncMock()
    ctx = ToolExecutionContext(db=mock_db, conversation_id=conv_id, allowed_document_ids=[doc_id])

    mock_db_result = MagicMock()
    mock_db_result.mappings.return_value.all.return_value = [
        {
            "id": doc_id,
            "filename": "annual_report.pdf",
            "page_count": 50,
            "chunks_count": 65,
            "size_bytes": 2 * 1024 * 1024,
        }
    ]
    mock_db.execute = AsyncMock(return_value=mock_db_result)

    res = await ctx.execute("list_documents", {})
    assert res["total_documents"] == 1
    assert res["documents"][0]["filename"] == "annual_report.pdf"
    assert res["documents"][0]["pages"] == 50
    assert res["documents"][0]["chunks"] == 65


@pytest.mark.asyncio
async def test_unknown_tool():
    ctx = ToolExecutionContext(db=AsyncMock(), conversation_id=uuid.uuid4(), allowed_document_ids=[])
    res = await ctx.execute("non_existent_tool", {})
    assert "error" in res
    assert "Unknown tool" in res["error"]



@pytest.mark.asyncio
async def test_security_empty_allowed_documents():
    conv_id = uuid.uuid4()
    # No allowed documents in conversation
    ctx = ToolExecutionContext(db=AsyncMock(), conversation_id=conv_id, allowed_document_ids=[])

    res = await ctx.execute("search_documents", {"query": "secret facts"})
    assert res["total_found"] == 0
    assert "No indexed documents" in res["note"]
