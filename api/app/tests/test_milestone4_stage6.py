"""
Tests for Stage 6, Milestone 4:
Search Service (vector, keyword, hybrid RRF) and REST endpoints.
"""

import asyncio
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_factory, engine
from app.main import app
from app.models.conversation import Conversation
from app.models.document import Chunk, Document
from app.services.embeddings import get_embedding_service
from app.services.search import search_chunks


async def _test_search_service_modes():
    """Verify vector, keyword, and hybrid search with RRF score breakdown."""
    doc_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    async with async_session_factory() as db:
        conv = Conversation(id=conv_id, title="Search Service Test")
        db.add(conv)

        doc = Document(
            id=doc_id,
            conversation_id=conv_id,
            filename="search_doc.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            sha256="fake_sha_search",
            status="ready",
            mode="rag",
            page_count=3,
            parse_status="parsed",
            index_status="indexed",
        )
        db.add(doc)

        c0_text = "PostgreSQL pgvector extension provides cosine distance and HNSW indexing for vectors."
        c1_text = "Neural networks and deep learning models utilize transformer architectures for attention."
        c2_text = "Docling layout segmentation performs document structure understanding and table parsing."

        emb_service = get_embedding_service()
        embs = await emb_service.embed_chunks([c0_text, c1_text, c2_text], task_type="RETRIEVAL_DOCUMENT")

        chunk0 = Chunk(
            document_id=doc_id,
            chunk_index=0,
            text=c0_text,
            embed_text=f"Document: search_doc.pdf\n{c0_text}",
            page_start=1,
            page_end=1,
            heading_path=["Database"],
            chunk_type="text",
            token_count=15,
            embedding=embs[0],
        )
        chunk1 = Chunk(
            document_id=doc_id,
            chunk_index=1,
            text=c1_text,
            embed_text=f"Document: search_doc.pdf\n{c1_text}",
            page_start=2,
            page_end=2,
            heading_path=["AI Models"],
            chunk_type="text",
            token_count=14,
            embedding=embs[1],
        )
        chunk2 = Chunk(
            document_id=doc_id,
            chunk_index=2,
            text=c2_text,
            embed_text=f"Document: search_doc.pdf\n{c2_text}",
            page_start=3,
            page_end=3,
            heading_path=["Parsing"],
            chunk_type="text",
            token_count=13,
            embedding=embs[2],
        )
        db.add_all([chunk0, chunk1, chunk2])
        await db.commit()

    try:
        async with async_session_factory() as db:
            # 1. Vector Search: query should retrieve database vector chunk first
            v_res = await search_chunks(db, query="vector similarity indexing in database", mode="vector", limit=3)
            assert v_res.mode == "vector"
            assert v_res.total_results > 0
            assert v_res.items[0].chunk_index == 0
            assert v_res.items[0].vector_score is not None

            # 2. Keyword Search: query 'transformer' should match chunk1 via tsvector
            k_res = await search_chunks(db, query="transformer neural", mode="keyword", limit=3)
            assert k_res.mode == "keyword"
            assert k_res.total_results > 0
            assert k_res.items[0].chunk_index == 1
            assert k_res.items[0].keyword_score is not None

            # 3. Hybrid Search: query combines vector + keyword with RRF
            h_res = await search_chunks(db, query="transformer architectures", mode="hybrid", limit=3)
            assert h_res.mode == "hybrid"
            assert h_res.total_results > 0
            top = h_res.items[0]
            assert top.chunk_index == 1
            assert top.score > 0
            assert top.vector_rank is not None or top.keyword_rank is not None

    finally:
        async with async_session_factory() as db:
            await db.execute(delete(Conversation).where(Conversation.id == conv_id))
            await db.commit()


async def _test_rest_endpoints():
    """Verify GET /chunks, POST /retry-index, and POST /api/search/debug endpoints."""
    doc_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    async with async_session_factory() as db:
        conv = Conversation(id=conv_id, title="API Endpoint Test")
        db.add(conv)

        doc = Document(
            id=doc_id,
            conversation_id=conv_id,
            filename="endpoint_doc.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="fake_sha_endpoint",
            status="ready",
            mode="rag",
            page_count=1,
            parse_status="parsed",
            index_status="indexed",
        )
        db.add(doc)

        c0 = Chunk(
            document_id=doc_id,
            chunk_index=0,
            text="REST API endpoint verification for chunking and search.",
            embed_text="Document: endpoint_doc.pdf\nREST API endpoint verification for chunking and search.",
            page_start=1,
            page_end=1,
            heading_path=["Testing"],
            chunk_type="text",
            token_count=10,
            embedding=[0.01] * 768,
        )
        db.add(c0)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            # 1. GET /api/documents/{id}/chunks
            res = await client.get(f"/api/documents/{doc_id}/chunks")
            assert res.status_code == 200
            data = res.json()
            assert data["document_id"] == str(doc_id)
            assert data["total_chunks"] == 1
            assert len(data["chunks"]) == 1
            assert data["chunks"][0]["chunk_index"] == 0

            # 2. POST /api/documents/{id}/retry-index
            retry_res = await client.post(f"/api/documents/{doc_id}/retry-index")
            assert retry_res.status_code == 202
            assert retry_res.json()["index_status"] == "pending"

            # 3. POST /api/search/debug
            search_res = await client.post(
                "/api/search/debug",
                json={
                    "query": "verification endpoint",
                    "mode": "keyword",
                    "document_ids": [str(doc_id)],
                    "limit": 5,
                },
            )
            assert search_res.status_code == 200
            s_data = search_res.json()
            assert s_data["query"] == "verification endpoint"
            assert s_data["mode"] == "keyword"
            assert s_data["total_results"] == 1
            assert s_data["items"][0]["document_id"] == str(doc_id)

        finally:
            await asyncio.sleep(1.5)
            async with async_session_factory() as db:
                await db.execute(delete(Conversation).where(Conversation.id == conv_id))
                await db.commit()


def test_search_service_modes():
    async def _run():
        await engine.dispose()
        try:
            await _test_search_service_modes()
        finally:
            await engine.dispose()
    asyncio.run(_run())


def test_rest_endpoints():
    async def _run():
        await engine.dispose()
        try:
            await _test_rest_endpoints()
        finally:
            await engine.dispose()
    asyncio.run(_run())


async def main():
    print("Testing search service modes...")
    await _test_search_service_modes()
    print("✓ Search service modes (vector, keyword, hybrid) passed")

    print("Testing REST endpoints (/chunks, /retry-index, /search/debug)...")
    await _test_rest_endpoints()
    print("✓ REST endpoints passed")

    await engine.dispose()
    print("ALL MILESTONE 4 TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
