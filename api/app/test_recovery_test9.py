"""
Test 9: Ingestion Delay & Startup Recovery Verification
"""
import asyncio
import os
import uuid
import requests
from app.db import async_session_factory
from app.models.document import Document
from app.models.conversation import Conversation
from app.services.ingestion import ingest_document
from app.main import run_startup_recovery
from app.test_acceptance_stage3 import create_sample_pdf, UPLOADS_DIR

async def test_recovery():
    print("=" * 60)
    print("TEST 9: STARTUP RECOVERY VERIFICATION")
    print("=" * 60)

    async with async_session_factory() as db:
        conv = Conversation(title="Recovery Test Conversation")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

        # 1. Document with file present on disk
        doc_with_file_id = uuid.uuid4()
        doc_dir = os.path.join(UPLOADS_DIR, str(doc_with_file_id))
        os.makedirs(doc_dir, exist_ok=True)
        pdf_path = os.path.join(doc_dir, "original.pdf")
        with open(pdf_path, "wb") as f:
            f.write(create_sample_pdf(num_pages=3))

        doc1 = Document(
            id=doc_with_file_id,
            conversation_id=conv.id,
            filename="recovered_doc.pdf",
            mime_type="application/pdf",
            size_bytes=os.path.getsize(pdf_path),
            sha256="fake_sha",
            status="processing"  # Stuck in processing before reboot
        )
        db.add(doc1)

        # 2. Document with file missing from disk
        doc_missing_file_id = uuid.uuid4()
        doc2 = Document(
            id=doc_missing_file_id,
            conversation_id=conv.id,
            filename="missing_file.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="fake_sha2",
            status="processing"  # Stuck in processing but disk was wiped
        )
        db.add(doc2)
        await db.commit()

    print(f"Created 2 simulated stuck 'processing' documents: {doc_with_file_id} (file exists) and {doc_missing_file_id} (file missing)")

    # Execute startup recovery
    print("Executing run_startup_recovery()...")
    await run_startup_recovery()

    # Allow background task to process
    await asyncio.sleep(1.0)

    # Verify outcomes
    async with async_session_factory() as db:
        res1 = await db.get(Document, doc_with_file_id)
        res2 = await db.get(Document, doc_missing_file_id)

        print(f"Document 1 (file existed): status='{res1.status}', page_count={res1.page_count}")
        assert res1.status == "ready", f"Expected ready, got {res1.status}"
        assert res1.page_count == 3

        print(f"Document 2 (file missing): status='{res2.status}', error='{res2.error}'")
        assert res2.status == "failed", f"Expected failed, got {res2.status}"
        assert "interrupted by server restart" in res2.error

    print("✔ Startup recovery successfully re-ingested existing files and marked missing files as failed.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_recovery())
