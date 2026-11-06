"""
Verification script for Stage 5 Milestone 4:
REST API Endpoints for Document Parsing.
"""
import asyncio
from pathlib import Path
import uuid
import httpx
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.conversation import Conversation
from app.models.document import Document
from app.services.storage import delete_document_files
from app.test_acceptance_stage4 import make_pdf


async def run_milestone4_tests():
    print("=" * 70)
    print("VERIFYING STAGE 5 MILESTONE 4: REST API ENDPOINTS")
    print("=" * 70)

    base_url = "http://localhost:8000"

    # 1. Setup a test conversation
    async with async_session_factory() as db:
        conv = Conversation(title="Milestone 4 Test Conversation")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conv_id = conv.id

    print(f"\n1. Created test conversation: {conv_id}")

    try:
        # Create a 3-page test PDF
        p1 = "API Specification Overview\nEndpoint GET /api/documents/{id}/parse provides status and summary."
        p2 = "Page Details and Pagination\nEndpoint GET /api/documents/{id}/pages returns paginated page metadata."
        p3 = "Download and Retry\nEndpoint GET /api/documents/{id}/parsed.md allows raw Markdown download."
        pdf_bytes = make_pdf([p1, p2, p3])

        async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
            # 2. Upload document via POST /api/conversations/{id}/documents
            print("\n2. Uploading 3-page PDF...")
            files = [("files", ("m4_spec.pdf", pdf_bytes, "application/pdf"))]
            upload_res = await client.post(f"/api/conversations/{conv_id}/documents", files=files)
            assert upload_res.status_code == 201, f"Upload failed: {upload_res.text}"
            doc_data = upload_res.json()[0]
            doc_id = doc_data["id"]
            print(f"   Uploaded document id: {doc_id}")

            # Wait a brief moment for ingestion inspection to complete
            await asyncio.sleep(2)

            # In rag_only mode, small PDF is mode='direct', status='ready', parse_status='skipped'
            initial_parse_res = await client.get(f"/api/documents/{doc_id}/parse")
            assert initial_parse_res.status_code == 200
            initial_parse = initial_parse_res.json()
            print(f"   Initial parse status after upload: {initial_parse['parse_status']} (mode={doc_data.get('mode')})")
            assert initial_parse["parse_status"] == "skipped"

            # 3. Trigger manual parse via POST /api/documents/{id}/parse/retry
            print("\n3. Triggering parse via POST /api/documents/{id}/parse/retry...")
            retry_res = await client.post(f"/api/documents/{doc_id}/parse/retry")
            assert retry_res.status_code == 200, f"Retry failed: {retry_res.text}"
            retry_data = retry_res.json()
            assert retry_data["parse_status"] == "pending"
            assert retry_data["pages_parsed"] == 0
            print("   - Retry endpoint immediately reset status to 'pending' and returned 200 (PASS)")

            # 4. Poll GET /api/documents/{id}/parse until parsed
            print("\n4. Testing GET /api/documents/{id}/parse polling...")
            max_wait = 90
            waited = 0
            parse_info = None

            while waited < max_wait:
                await asyncio.sleep(2)
                waited += 2
                res = await client.get(f"/api/documents/{doc_id}/parse")
                assert res.status_code == 200, f"Get parse status failed: {res.text}"
                parse_info = res.json()
                status = parse_info.get("parse_status")
                if status in ("parsed", "failed"):
                    break

            print(f"   Parse status after ~{waited}s: {parse_info['parse_status']}")
            assert parse_info["parse_status"] == "parsed", f"Parse failed: {parse_info.get('parse_error')}"
            assert parse_info["parser_name"] == "docling"
            assert parse_info["pages_parsed"] == 3
            assert parse_info["total_pages"] == 3
            assert parse_info["duration_seconds"] is not None and parse_info["duration_seconds"] > 0
            assert parse_info["warnings_summary"] is not None
            ws = parse_info["warnings_summary"]
            print(f"   Warnings summary: total_chars={ws['total_characters']}, tables={ws['pages_with_tables']}, figures={ws['pages_with_figures']}, low_text={ws['low_text_pages']}")
            assert ws["total_characters"] > 100
            print("   - GET /api/documents/{id}/parse: PASS")

            # Test 404 on parse endpoint
            missing_id = uuid.uuid4()
            res_404 = await client.get(f"/api/documents/{missing_id}/parse")
            assert res_404.status_code == 404
            print("   - GET /api/documents/{fake_id}/parse -> 404: PASS")

            # 5. Test GET /api/documents/{id}/pages (Paginated)
            print("\n5. Testing GET /api/documents/{id}/pages (Pagination)...")
            # Page 1 with limit 2
            res_p1 = await client.get(f"/api/documents/{doc_id}/pages?page=1&limit=2")
            assert res_p1.status_code == 200
            p1_data = res_p1.json()
            assert p1_data["total"] == 3
            assert p1_data["page"] == 1
            assert p1_data["limit"] == 2
            assert p1_data["total_pages"] == 2
            assert len(p1_data["items"]) == 2
            assert p1_data["items"][0]["page_no"] == 1
            assert p1_data["items"][1]["page_no"] == 2
            print("   - Page 1 (limit 2): 2 items, total=3, total_pages=2 (PASS)")

            # Page 2 with limit 2
            res_p2 = await client.get(f"/api/documents/{doc_id}/pages?page=2&limit=2")
            assert res_p2.status_code == 200
            p2_data = res_p2.json()
            assert p2_data["page"] == 2
            assert len(p2_data["items"]) == 1
            assert p2_data["items"][0]["page_no"] == 3
            print("   - Page 2 (limit 2): 1 item (page 3) (PASS)")

            # 6. Test GET /api/documents/{id}/pages/{page_no} (Single Page Detail)
            print("\n6. Testing GET /api/documents/{id}/pages/{page_no}...")
            res_page1 = await client.get(f"/api/documents/{doc_id}/pages/1")
            assert res_page1.status_code == 200
            page1 = res_page1.json()
            assert page1["page_no"] == 1
            assert "API Specification Overview" in page1["markdown"] or "API Specification Overview" in page1["plain_text"]
            assert page1["char_count"] > 0
            print(f"   - Page 1 detail: char_count={page1['char_count']}, markdown length={len(page1['markdown'])} (PASS)")

            # Non-existent page number
            res_page_missing = await client.get(f"/api/documents/{doc_id}/pages/99")
            assert res_page_missing.status_code == 404
            assert "Page 99 not found" in res_page_missing.json()["detail"]
            print("   - Non-existent page 99 -> 404: PASS")

            # 7. Test GET /api/documents/{id}/parsed.md (Attachment Download)
            print("\n7. Testing GET /api/documents/{id}/parsed.md...")
            res_md = await client.get(f"/api/documents/{doc_id}/parsed.md")
            assert res_md.status_code == 200
            assert res_md.headers.get("content-type", "").startswith("text/markdown")
            assert 'attachment; filename="m4_spec.parsed.md"' in res_md.headers.get("content-disposition", "")
            md_content = res_md.text
            assert "<!-- Page 1 -->" in md_content
            assert "<!-- Page 2 -->" in md_content
            assert "<!-- Page 3 -->" in md_content
            print(f"   - Downloaded parsed.md ({len(md_content)} bytes, attachment disposition): PASS")

            # 8. Test retry validation: non-PDF document should return 400
            print("\n8. Testing error handling & validations...")
            txt_files = [("files", ("test.txt", b"simple plain text file", "text/plain"))]
            txt_res = await client.post(f"/api/conversations/{conv_id}/documents", files=txt_files)
            txt_id = txt_res.json()[0]["id"]
            txt_retry = await client.post(f"/api/documents/{txt_id}/parse/retry")
            assert txt_retry.status_code == 400
            assert "Only PDF documents can be parsed" in txt_retry.json()["detail"]
            print("   - Retry non-PDF document returns 400: PASS")

            # 404 on non-existent document for pages, page detail, parsed.md
            res_pages_404 = await client.get(f"/api/documents/{missing_id}/pages")
            assert res_pages_404.status_code == 404
            res_pdetail_404 = await client.get(f"/api/documents/{missing_id}/pages/1")
            assert res_pdetail_404.status_code == 404
            res_md_404 = await client.get(f"/api/documents/{missing_id}/parsed.md")
            assert res_md_404.status_code == 404
            print("   - 404 validation for missing document on all endpoints: PASS")

        print("\n" + "=" * 70)
        print("ALL MILESTONE 4 REST API TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        async with async_session_factory() as db:
            await db.execute(delete(Conversation).where(Conversation.id == conv_id))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(run_milestone4_tests())
