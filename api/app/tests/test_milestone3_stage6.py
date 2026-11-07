"""
Tests for Stage 6, Milestone 3:
Chunks table, indexing pipeline, idempotent indexing, and startup recovery.
"""

import asyncio
from datetime import datetime, timezone
import json
import shutil
import uuid
import pytest
from sqlalchemy import delete, select, text

from app.db import async_session_factory, engine
from app.models.conversation import Conversation
from app.models.document import Chunk, Document, DocumentPage
from app.main import run_startup_recovery
from app.services.ingestion import index_document_task
from app.services.storage import get_document_dir, get_document_file_path, get_document_parsed_dir


async def _test_chunks_table_schema():
    """Verify that chunks table exists with vector and tsv columns in PostgreSQL."""
    async with async_session_factory() as db:
        res = await db.execute(text("""
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_name = 'chunks'
            ORDER BY ordinal_position;
        """))
        cols = {r[0]: (r[1], r[2]) for r in res.fetchall()}

        assert "id" in cols
        assert "document_id" in cols
        assert "chunk_index" in cols
        assert "text" in cols
        assert "embed_text" in cols
        assert "embedding" in cols
        assert "tsv" in cols
        assert cols["embedding"][1] == "vector"
        assert cols["tsv"][1] == "tsvector"


async def _test_index_document_pipeline_and_idempotency():
    """
    Test end-to-end indexing pipeline:
    1. Create test document with docling.json on disk and parsed status.
    2. Run index_document_task.
    3. Assert chunks inserted, embedding dimension is 768, tsv generated, index_status == 'indexed'.
    4. Re-run index_document_task to verify idempotency (no duplicate key errors).
    """
    doc_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    async with async_session_factory() as db:
        conv = Conversation(id=conv_id, title="Test Index Pipeline")
        db.add(conv)

        doc = Document(
            id=doc_id,
            conversation_id=conv_id,
            filename="pipeline_test.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="fake_sha256_index_pipeline",
            status="ready",
            mode="rag",
            page_count=2,
            parse_status="parsed",
            index_status="pending",
        )
        db.add(doc)

        p1 = DocumentPage(
            document_id=doc_id,
            page_no=1,
            markdown="# Architecture Overview\nDocling provides accurate document layout parsing.",
            plain_text="Architecture Overview Docling provides accurate document layout parsing.",
            char_count=65,
        )
        p2 = DocumentPage(
            document_id=doc_id,
            page_no=2,
            markdown="## Search and Retrieval\nVectors and pgvector enable hybrid search with RRF.",
            plain_text="Search and Retrieval Vectors and pgvector enable hybrid search with RRF.",
            char_count=71,
        )
        db.add_all([p1, p2])
        await db.commit()

    try:
        # Create disk directory and mock docling.json
        parsed_dir = get_document_parsed_dir(doc_id)
        parsed_dir.mkdir(parents=True, exist_ok=True)
        docling_json_path = parsed_dir / "docling.json"

        mock_docling = {
            "schema_name": "DoclingDocument",
            "version": "1.10.0",
            "name": "pipeline_test.pdf",
            "texts": [
                {
                    "self_ref": "#/texts/1",
                    "label": "section_heading",
                    "text": "Architecture Overview",
                    "prov": [{"page_no": 1}],
                },
                {
                    "self_ref": "#/texts/2",
                    "label": "text",
                    "text": "Docling provides accurate document layout parsing for AI systems.",
                    "prov": [{"page_no": 1}],
                },
                {
                    "self_ref": "#/texts/3",
                    "label": "section_heading",
                    "text": "Search and Retrieval",
                    "prov": [{"page_no": 2}],
                },
                {
                    "self_ref": "#/texts/4",
                    "label": "text",
                    "text": "Vectors and pgvector enable hybrid search with reciprocal rank fusion.",
                    "prov": [{"page_no": 2}],
                },
            ],
            "tables": [],
        }
        with open(docling_json_path, "w", encoding="utf-8") as f:
            json.dump(mock_docling, f)

        # 1. First indexing run
        await index_document_task(doc_id)

        async with async_session_factory() as db:
            d_res = await db.execute(select(Document).where(Document.id == doc_id))
            saved_doc = d_res.scalar_one()
            assert saved_doc.index_status == "indexed"
            assert saved_doc.chunks_count > 0
            assert saved_doc.indexed_at is not None

            c_res = await db.execute(select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.chunk_index))
            chunks = c_res.scalars().all()
            assert len(chunks) == saved_doc.chunks_count
            for c in chunks:
                assert c.embedding is not None
                assert len(c.embedding) == 768
                assert c.tsv is not None  # Postgres tsvector generated automatically!
                assert c.token_count > 0
                assert c.page_start in (1, 2)

        # 2. Idempotency test: run again on same document
        await index_document_task(doc_id)

        async with async_session_factory() as db:
            d_res = await db.execute(select(Document).where(Document.id == doc_id))
            saved_doc = d_res.scalar_one()
            assert saved_doc.index_status == "indexed"

            c_res = await db.execute(select(Chunk).where(Chunk.document_id == doc_id))
            chunks = c_res.scalars().all()
            # Still exactly the same number of chunks (no duplicates)
            assert len(chunks) == saved_doc.chunks_count

    finally:
        # Cleanup
        async with async_session_factory() as db:
            await db.execute(delete(Conversation).where(Conversation.id == conv_id))
            await db.commit()
        doc_dir = get_document_dir(doc_id)
        if doc_dir.exists():
            shutil.rmtree(doc_dir, ignore_errors=True)


async def _test_startup_recovery_reindexes_stuck_documents():
    """Verify that startup recovery picks up documents stuck in 'indexing' and completes them."""
    doc_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    async with async_session_factory() as db:
        conv = Conversation(id=conv_id, title="Test Recovery")
        db.add(conv)

        doc = Document(
            id=doc_id,
            conversation_id=conv_id,
            filename="recovery_test.pdf",
            mime_type="application/pdf",
            size_bytes=512,
            sha256="fake_sha256_recovery",
            status="ready",
            mode="rag",
            page_count=1,
            parse_status="parsed",
            index_status="indexing",  # Interrupted in the middle of indexing!
        )
        db.add(doc)

        p1 = DocumentPage(
            document_id=doc_id,
            page_no=1,
            markdown="# Crash Recovery\nTesting startup recovery for interrupted indexing pipeline.",
            plain_text="Crash Recovery Testing startup recovery for interrupted indexing pipeline.",
            char_count=73,
        )
        db.add(p1)
        await db.commit()

    # Create dummy original file so recovery doesn't fail on missing file
    fpath = get_document_file_path(doc_id, "application/pdf")
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_bytes(b"%PDF-1.4 mock")

    try:
        # Run startup recovery
        await run_startup_recovery()

        # Allow background task to complete
        for _ in range(20):
            await asyncio.sleep(0.5)
            async with async_session_factory() as db:
                d_res = await db.execute(select(Document).where(Document.id == doc_id))
                d = d_res.scalar_one_or_none()
                if d and d.index_status == "indexed":
                    break

        async with async_session_factory() as db:
            d_res = await db.execute(select(Document).where(Document.id == doc_id))
            recovered_doc = d_res.scalar_one()
            assert recovered_doc.index_status == "indexed"
            assert recovered_doc.chunks_count > 0

    finally:
        async with async_session_factory() as db:
            await db.execute(delete(Conversation).where(Conversation.id == conv_id))
            await db.commit()
        doc_dir = get_document_dir(doc_id)
        if doc_dir.exists():
            shutil.rmtree(doc_dir, ignore_errors=True)


async def main():
    print("Testing chunks table schema...")
    await _test_chunks_table_schema()
    print("✓ Chunks table schema verified")

    print("Testing indexing pipeline and idempotency...")
    await _test_index_document_pipeline_and_idempotency()
    print("✓ Indexing pipeline & idempotency verified")

    print("Testing startup recovery for stuck indexing documents...")
    await _test_startup_recovery_reindexes_stuck_documents()
    print("✓ Startup recovery verified")

    await engine.dispose()
    print("ALL MILESTONE 3 TESTS PASSED!")


def test_chunks_table_schema():
    async def _run():
        await engine.dispose()
        try:
            await _test_chunks_table_schema()
        finally:
            await engine.dispose()
    asyncio.run(_run())


def test_index_document_pipeline_and_idempotency():
    async def _run():
        await engine.dispose()
        try:
            await _test_index_document_pipeline_and_idempotency()
        finally:
            await engine.dispose()
    asyncio.run(_run())


def test_startup_recovery_reindexes_stuck_documents():
    async def _run():
        await engine.dispose()
        try:
            await _test_startup_recovery_reindexes_stuck_documents()
        finally:
            await engine.dispose()
    asyncio.run(_run())


if __name__ == "__main__":
    asyncio.run(main())
