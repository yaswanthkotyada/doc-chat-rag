"""
Verification script for Stage 5 Milestone 3:
Database Schema, Disk Storage Layout, Background Ingestion & Startup Recovery.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import uuid
import httpx
from sqlalchemy import delete, select

from app.config import settings
from app.db import async_session_factory
from app.models.conversation import Conversation
from app.models.document import Document, DocumentPage
from app.services.ingestion import ingest_document, parse_document_task
from app.services.storage import (
    delete_document_files,
    get_document_dir,
    get_document_file_path,
    get_document_parsed_json_path,
    get_document_parsed_md_path,
)
from app.main import run_startup_recovery
from app.test_acceptance_stage4 import make_pdf


async def run_milestone3_tests():
    print("=" * 70)
    print("VERIFYING STAGE 5 MILESTONE 3: DB SCHEMA, STORAGE & INGESTION QUEUE")
    print("=" * 70)

    # 1. Setup a test conversation
    async with async_session_factory() as db:
        conv = Conversation(title="Milestone 3 Test Conversation")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conv_id = conv.id

    print(f"\n1. Created test conversation: {conv_id}")

    try:
        # Create a 3-page test PDF
        p1 = "Milestone 3 Overview\nDatabase models and alembic migration 004 are verified."
        p2 = "Queue and Concurrency\nBackground tasks manage docling parsing with asyncio.Semaphore."
        p3 = "Storage Layout\nArtifacts are saved to /data/uploads/{document_id}/parsed/."
        pdf_bytes = make_pdf([p1, p2, p3])

        # Test A: Ingestion of RAG-mode document triggers parsing
        doc_id = uuid.uuid4()
        doc_dir = get_document_dir(doc_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        pdf_file = get_document_file_path(doc_id, "application/pdf")
        pdf_file.write_bytes(pdf_bytes)

        async with async_session_factory() as db:
            doc = Document(
                id=doc_id,
                conversation_id=conv_id,
                filename="milestone3_test.pdf",
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                sha256="dummy_hash_m3",
                status="uploading",
                mode="rag",  # explicitly test rag mode flow
            )
            db.add(doc)
            await db.commit()

        print(f"\n2. Testing Ingestion & Parsing flow for document {doc_id}...")
        # Temporarily configure test settings
        orig_direct_pages = settings.DIRECT_MAX_PAGES
        orig_parse_mode = settings.PARSE_MODE
        orig_ocr = settings.PARSE_OCR_ENABLED
        settings.DIRECT_MAX_PAGES = 2
        settings.PARSE_MODE = "rag_only"
        settings.PARSE_OCR_ENABLED = False

        try:
            # Trigger ingestion
            await ingest_document(doc_id)

            # Ingestion marks status='processing' and parse_status='pending' and launches task
            # Wait for parsing to finish (poll up to 90s)
            max_wait = 90
            waited = 0
            final_doc = None
            while waited < max_wait:
                await asyncio.sleep(2)
                waited += 2
                async with async_session_factory() as db:
                    stmt = select(Document).where(Document.id == doc_id)
                    res = await db.execute(stmt)
                    final_doc = res.scalar_one_or_none()
                    if final_doc and final_doc.parse_status in ("parsed", "failed"):
                        break

            print(f"   Parsing finished in ~{waited}s with status={final_doc.status}, mode={final_doc.mode}, parse_status={final_doc.parse_status}")
            assert final_doc is not None
            assert final_doc.mode == "rag", f"Expected mode 'rag', got {final_doc.mode}"
            assert final_doc.parse_status == "parsed", f"Expected 'parsed', got {final_doc.parse_status}: {final_doc.parse_error}"
            assert final_doc.status == "ready", f"Expected document status 'ready', got {final_doc.status}"
            assert final_doc.pages_parsed == 3, f"Expected 3 pages parsed, got {final_doc.pages_parsed}"
            assert final_doc.parser_name == "docling"
            print("   - Document status and parse_status: PASS")
        finally:
            settings.DIRECT_MAX_PAGES = orig_direct_pages
            settings.PARSE_MODE = orig_parse_mode
            settings.PARSE_OCR_ENABLED = orig_ocr

        # Verify DocumentPage rows in database
        async with async_session_factory() as db:
            p_stmt = select(DocumentPage).where(DocumentPage.document_id == doc_id).order_by(DocumentPage.page_no)
            p_res = await db.execute(p_stmt)
            pages = p_res.scalars().all()

        assert len(pages) == 3, f"Expected 3 page rows, got {len(pages)}"
        for i, page in enumerate(pages, start=1):
            assert page.page_no == i
            assert len(page.markdown) > 0
            assert page.char_count > 0
            print(f"   - Page {page.page_no}: {page.char_count} chars, table={page.has_table}, fig={page.has_figure}")
        print("   - Database document_pages records: PASS")

        # Verify disk artifacts
        json_path = get_document_parsed_json_path(doc_id)
        md_path = get_document_parsed_md_path(doc_id)
        assert json_path.exists(), f"Missing parsed JSON file at {json_path}"
        assert md_path.exists(), f"Missing parsed Markdown file at {md_path}"
        raw_json = json.loads(json_path.read_text(encoding="utf-8"))
        assert "schema_name" in raw_json or "batches" in raw_json
        full_md = md_path.read_text(encoding="utf-8")
        assert "<!-- Page 1 -->" in full_md
        print(f"   - Disk artifacts exist: {json_path.name} ({json_path.stat().st_size} bytes), {md_path.name} ({md_path.stat().st_size} bytes) (PASS)")

        # Test B: Cascade Deletion
        print("\n3. Testing document deletion cascade...")
        async with async_session_factory() as db:
            del_stmt = delete(Document).where(Document.id == doc_id)
            await db.execute(del_stmt)
            await db.commit()

        delete_document_files(doc_id)

        # Check DB pages deleted by cascade
        async with async_session_factory() as db:
            chk_stmt = select(DocumentPage).where(DocumentPage.document_id == doc_id)
            chk_res = await db.execute(chk_stmt)
            remaining_pages = chk_res.scalars().all()
        assert len(remaining_pages) == 0, "DocumentPage records were not cascade-deleted"
        assert not doc_dir.exists(), "Document directory was not deleted from disk"
        print("   - Cascade deletion of DB rows & disk folder: PASS")

        # Test C: Startup Recovery
        print("\n4. Testing startup recovery with stuck parsing document...")
        recovery_doc_id = uuid.uuid4()
        rec_dir = get_document_dir(recovery_doc_id)
        rec_dir.mkdir(parents=True, exist_ok=True)
        rec_file = get_document_file_path(recovery_doc_id, "application/pdf")
        rec_file.write_bytes(pdf_bytes)

        async with async_session_factory() as db:
            stuck_doc = Document(
                id=recovery_doc_id,
                conversation_id=conv_id,
                filename="stuck_parse.pdf",
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                sha256="stuck_hash",
                status="processing",
                parse_status="parsing",
                mode="rag",
            )
            db.add(stuck_doc)
            # Add an invalid partial page to verify it gets cleared
            dummy_page = DocumentPage(
                document_id=recovery_doc_id,
                page_no=999,
                markdown="partial junk",
                plain_text="partial junk",
                char_count=12,
            )
            db.add(dummy_page)
            await db.commit()

        print("   Simulated stuck document with partial page. Running startup recovery...")
        orig_ocr = settings.PARSE_OCR_ENABLED
        settings.PARSE_OCR_ENABLED = False
        try:
            await run_startup_recovery()

            # Wait for recovery task to complete
            waited = 0
            rec_final = None
            while waited < 90:
                await asyncio.sleep(2)
                waited += 2
                async with async_session_factory() as db:
                    stmt = select(Document).where(Document.id == recovery_doc_id)
                    res = await db.execute(stmt)
                    rec_final = res.scalar_one_or_none()
                    if rec_final and rec_final.parse_status in ("parsed", "failed"):
                        break
        finally:
            settings.PARSE_OCR_ENABLED = orig_ocr

        assert rec_final is not None
        assert rec_final.parse_status == "parsed", f"Recovery failed: {rec_final.parse_status}: {rec_final.parse_error}"
        assert rec_final.status == "ready"

        # Verify dummy page 999 was cleared and replaced with pages 1, 2, 3
        async with async_session_factory() as db:
            p_stmt = select(DocumentPage).where(DocumentPage.document_id == recovery_doc_id).order_by(DocumentPage.page_no)
            p_res = await db.execute(p_stmt)
            rec_pages = p_res.scalars().all()
        page_numbers = [p.page_no for p in rec_pages]
        assert page_numbers == [1, 2, 3], f"Expected pages [1, 2, 3], got {page_numbers}"
        print(f"   - Startup recovery cleanly cleared partial state and parsed document: PASS (pages {page_numbers})")

        # Clean up recovery doc
        async with async_session_factory() as db:
            await db.execute(delete(Document).where(Document.id == recovery_doc_id))
            await db.commit()
        delete_document_files(recovery_doc_id)

        # Test D: Unreachable Docling Service Handling
        print("\n5. Testing error handling when Docling is unreachable...")
        bad_doc_id = uuid.uuid4()
        bad_dir = get_document_dir(bad_doc_id)
        bad_dir.mkdir(parents=True, exist_ok=True)
        bad_file = get_document_file_path(bad_doc_id, "application/pdf")
        bad_file.write_bytes(pdf_bytes)

        async with async_session_factory() as db:
            bad_doc = Document(
                id=bad_doc_id,
                conversation_id=conv_id,
                filename="unreachable_test.pdf",
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                sha256="bad_hash",
                status="processing",
                parse_status="pending",
                mode="rag",
            )
            db.add(bad_doc)
            await db.commit()

        # Temporarily override DOCLING_URL to an unreachable address
        orig_url = settings.DOCLING_URL
        settings.DOCLING_URL = "http://127.0.0.1:59999"

        try:
            await parse_document_task(bad_doc_id)
        finally:
            settings.DOCLING_URL = orig_url

        async with async_session_factory() as db:
            stmt = select(Document).where(Document.id == bad_doc_id)
            res = await db.execute(stmt)
            failed_doc = res.scalar_one_or_none()

        assert failed_doc is not None
        assert failed_doc.parse_status == "failed"
        assert failed_doc.parse_error == "Parsing service unavailable"
        assert failed_doc.status == "failed"
        assert failed_doc.error == "Parsing service unavailable"
        print("   - Graceful failure when Docling unreachable: PASS")

        # Clean up bad doc
        async with async_session_factory() as db:
            await db.execute(delete(Document).where(Document.id == bad_doc_id))
            await db.commit()
        delete_document_files(bad_doc_id)

        print("\n" + "=" * 70)
        print("ALL MILESTONE 3 TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        async with async_session_factory() as db:
            await db.execute(delete(Conversation).where(Conversation.id == conv_id))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(run_milestone3_tests())
