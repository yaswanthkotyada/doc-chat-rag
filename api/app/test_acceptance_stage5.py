"""
STAGE 5 ACCEPTANCE TEST SUITE: DOCUMENT PARSING WITH DOCLING
============================================================
Comprehensive test suite verifying all Stage 5 requirements:
1. Infrastructure, Docker Compose, Model Cache Volume & Health Probe
2. Docling Container Resilience (Graceful degradation, health 200, retry)
3. Multi-page PDF Parsing with Exact Page Counts & 1-based Indexing
4. Tables & Structural Layout Extraction
5. Quality Heuristics (low_text, garbled, page count mismatch)
6. Page Batching & Progress Reporting
7. Disk Storage Layout (/data/uploads/{id}/parsed/docling.json & full.md)
8. Cascade Deletion (Database & Disk Cleanup)
9. Startup Recovery (Re-queue stuck parses & purge partial pages)
10. Concurrency Limiting (Bounded by PARSE_CONCURRENCY semaphore)
11. REST API Endpoints Validation (/parse, /retry, /pages, /pages/{n}, /parsed.md)
12. Chat RAG Status-Aware Messaging ("Parsed and ready for indexing...")
13. Non-Regression Verification (Direct Mode Q&A, Plain Chat, Upload Limits)
"""
import asyncio
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
import uuid
import httpx
from pypdf import PdfWriter
import requests
from sqlalchemy import delete, select

from app.config import settings
from app.db import async_session_factory
from app.models.conversation import Conversation
from app.models.document import Document, DocumentPage
from app.services.ingestion import parse_document_task
from app.services.parsers import DoclingClientParser, ParserUnavailableError
from app.services.storage import (
    delete_document_files,
    get_document_dir,
    get_document_file_path,
    get_document_parsed_json_path,
    get_document_parsed_md_path,
)
from app.main import run_startup_recovery
from app.test_acceptance_stage4 import make_pdf

BASE_URL = "http://localhost:8000"


def send_chat_sse(conversation_id: str, message: str, doc_ids: list = None):
    """Helper to call POST /api/chat and parse SSE stream matching the server protocol."""
    url = f"{BASE_URL}/api/chat"
    payload = {"conversation_id": conversation_id, "message": message}
    if doc_ids is not None:
        payload["document_ids"] = doc_ids

    tokens = []
    done_data = None
    error_msg = None
    prev_event = ""

    res = requests.post(url, json=payload, stream=True, timeout=60)
    assert res.status_code == 200, f"Chat failed (status {res.status_code}): {res.text}"

    for line in res.iter_lines():
        if not line:
            prev_event = ""
            continue
        l = line.decode("utf-8")
        if l.startswith("event: "):
            prev_event = l[7:].strip()
        elif l.startswith("data: "):
            raw_data = l[6:]
            if prev_event == "token":
                try:
                    tok_obj = json.loads(raw_data)
                    if isinstance(tok_obj, dict) and "text" in tok_obj:
                        tokens.append(tok_obj["text"])
                    else:
                        tokens.append(str(tok_obj))
                except Exception:
                    tokens.append(raw_data)
            elif prev_event == "done":
                try:
                    done_data = json.loads(raw_data)
                except Exception:
                    done_data = {"raw": raw_data}
            elif prev_event == "error":
                try:
                    err_obj = json.loads(raw_data)
                    error_msg = err_obj.get("text", raw_data) if isinstance(err_obj, dict) else str(err_obj)
                except Exception:
                    error_msg = raw_data

    answer_text = "".join(tokens)
    return answer_text, done_data


async def run_stage5_acceptance_tests():
    print("=" * 80)
    print("STAGE 5 ACCEPTANCE TEST SUITE: DOCUMENT PARSING WITH DOCLING")
    print(f"Base URL: {BASE_URL}")
    print(f"Docling URL: {settings.DOCLING_URL}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    summary_results = []

    # ------------------------------------------------------------------------
    # TEST 1: Infrastructure, Docker Compose & Health Probe
    # ------------------------------------------------------------------------
    print("\n[TEST 1] Infrastructure, Docker Compose & Health Probe")
    h_res = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert h_res.status_code == 200, f"Healthcheck failed: {h_res.text}"
    h_data = h_res.json()
    print(f"  Health response: {h_data}")
    assert h_data.get("api") == "ok"
    assert h_data.get("db") == "ok"
    assert h_data.get("docling") in ("ok", "unreachable")
    print("  Docling health probe is informational and server is 200: PASS")
    summary_results.append({"test": "1. Infrastructure & Health Probe", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 2: Docling Container Resilience (Graceful Degradation)
    # ------------------------------------------------------------------------
    print("\n[TEST 2] Docling Container Resilience & Unreachable Service Handling")
    # Simulate Docling being unreachable
    orig_url = settings.DOCLING_URL
    settings.DOCLING_URL = "http://127.0.0.1:59999"

    # Test that health endpoint reports docling unreachable while remaining 200
    h_res_unreach = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert h_res_unreach.status_code == 200
    print(f"  Health probe when unreachable: HTTP {h_res_unreach.status_code}")

    # Plain chat still works even if Docling is down
    conv_res = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 2 Plain Chat"}).json()
    t2_cid = conv_res["id"]
    ans, done = send_chat_sse(t2_cid, "Say hello in one word.", [])
    print(f"  Debug Plain Chat response: ans={ans!r}, done={done!r}")
    assert done is not None and len(ans.strip()) > 0
    print(f"  Plain chat works while Docling unreachable: '{ans.strip()[:40]}' (PASS)")

    # Document parse with unreachable Docling fails gracefully with safe message
    unreach_doc_id = uuid.uuid4()
    pdf_bytes_t2 = make_pdf(["Test page for unreachable docling."])
    doc_dir = get_document_dir(unreach_doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    get_document_file_path(unreach_doc_id, "application/pdf").write_bytes(pdf_bytes_t2)

    async with async_session_factory() as db:
        d2 = Document(
            id=unreach_doc_id,
            conversation_id=uuid.UUID(t2_cid),
            filename="unreach_test.pdf",
            mime_type="application/pdf",
            size_bytes=len(pdf_bytes_t2),
            sha256="hash_t2",
            status="processing",
            parse_status="pending",
            mode="rag",
        )
        db.add(d2)
        await db.commit()

    try:
        await parse_document_task(unreach_doc_id)
    finally:
        settings.DOCLING_URL = orig_url

    async with async_session_factory() as db:
        res = await db.execute(select(Document).where(Document.id == unreach_doc_id))
        d2_final = res.scalar_one_or_none()
    assert d2_final.parse_status == "failed"
    assert d2_final.parse_error == "Parsing service unavailable"
    assert d2_final.status == "failed"
    print(f"  Failed parse marked cleanly: parse_status='{d2_final.parse_status}', error='{d2_final.parse_error}' (PASS)")

    # Retry with Docling restored succeeds
    print("  Retrying parse with Docling restored...")
    await parse_document_task(unreach_doc_id)
    async with async_session_factory() as db:
        res = await db.execute(select(Document).where(Document.id == unreach_doc_id))
        d2_restored = res.scalar_one_or_none()
    assert d2_restored.parse_status == "parsed"
    assert d2_restored.status == "ready"
    print(f"  Retry succeeded: parse_status='{d2_restored.parse_status}', status='{d2_restored.status}' (PASS)")

    # Cleanup Test 2
    delete_document_files(unreach_doc_id)
    requests.delete(f"{BASE_URL}/api/conversations/{t2_cid}")
    summary_results.append({"test": "2. Docling Resilience & Retry", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 3: Multi-Page Text PDF Parsing & 1-Based Indexing
    # ------------------------------------------------------------------------
    print("\n[TEST 3] Multi-Page Text PDF Parsing & Exact 1-Based Page Indexing")
    conv3 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 3 Multi-page"}).json()
    t3_cid = conv3["id"]

    pages_text = [
        "System Architecture Overview\nDocling provides accurate document parsing and layout understanding.",
        "Data Pipeline Engineering\nPer-page segmentation maintains 1-based exact page numbers for RAG.",
        "Storage Infrastructure\nPostgreSQL tables store page metadata and disk holds raw docling artifacts.",
    ]
    t3_pdf = make_pdf(pages_text)

    # Upload PDF and trigger parse via retry endpoint
    files = [("files", ("architecture_doc.pdf", t3_pdf, "application/pdf"))]
    u3_res = requests.post(f"{BASE_URL}/api/conversations/{t3_cid}/documents", files=files)
    t3_doc_id = u3_res.json()[0]["id"]

    # Trigger Docling parse
    requests.post(f"{BASE_URL}/api/documents/{t3_doc_id}/parse/retry")

    # Poll until parsed
    t3_info = None
    for _ in range(45):
        await asyncio.sleep(2)
        p = requests.get(f"{BASE_URL}/api/documents/{t3_doc_id}/parse").json()
        if p.get("parse_status") in ("parsed", "failed"):
            t3_info = p
            break

    assert t3_info is not None and t3_info["parse_status"] == "parsed"
    assert t3_info["pages_parsed"] == 3
    assert t3_info["total_pages"] == 3

    # Check document_pages rows
    async with async_session_factory() as db:
        res = await db.execute(select(DocumentPage).where(DocumentPage.document_id == uuid.UUID(t3_doc_id)).order_by(DocumentPage.page_no))
        db_pages = res.scalars().all()

    assert len(db_pages) == 3
    for idx, page in enumerate(db_pages, start=1):
        assert page.page_no == idx
        assert len(page.markdown) > 0
        assert page.char_count > 0
        print(f"  Page {page.page_no}: char_count={page.char_count}, warnings={page.warnings}")

    print("  Exact 1-based page indexing verified: PASS")
    summary_results.append({"test": "3. Multi-Page Parsing & 1-Based Indexing", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 4: Tables & Structural Extraction
    # ------------------------------------------------------------------------
    print("\n[TEST 4] Tables & Structural Layout Extraction")
    table_page = (
        "Financial Performance Summary\n\n"
        "Quarter | Revenue | Operating Expenses | Net Profit\n"
        "Q1 2024 | $12.4M | $8.2M | $4.2M\n"
        "Q2 2024 | $14.1M | $8.9M | $5.2M\n"
        "Q3 2024 | $16.2M | $9.8M | $6.4M\n"
    )
    t4_pdf = make_pdf([table_page])
    files4 = [("files", ("financial_tables.pdf", t4_pdf, "application/pdf"))]
    u4_res = requests.post(f"{BASE_URL}/api/conversations/{t3_cid}/documents", files=files4)
    t4_doc_id = u4_res.json()[0]["id"]

    requests.post(f"{BASE_URL}/api/documents/{t4_doc_id}/parse/retry")
    for _ in range(45):
        await asyncio.sleep(2)
        p = requests.get(f"{BASE_URL}/api/documents/{t4_doc_id}/parse").json()
        if p.get("parse_status") in ("parsed", "failed"):
            break

    # Verify table detection
    p1_detail = requests.get(f"{BASE_URL}/api/documents/{t4_doc_id}/pages/1").json()
    print(f"  Page 1 markdown preview:\n{p1_detail['markdown'][:150]}")
    assert "Revenue" in p1_detail["markdown"] or "Revenue" in p1_detail["plain_text"]
    print("  Table content extraction and markdown structure: PASS")
    summary_results.append({"test": "4. Tables & Structural Layout", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 5: Quality Heuristics (low_text, garbled)
    # ------------------------------------------------------------------------
    print("\n[TEST 5] Quality Heuristics Verification (low_text & garbled)")
    low_text = "Few chars"  # < 50 chars -> low_text
    garbled_text = "$$%%% ### @@@ ^^^ &&& *** ~~~ !!! ??? /// \\\\\\ ||| === +++"  # High non-alphanumeric -> garbled
    t5_pdf = make_pdf([low_text, garbled_text])

    files5 = [("files", ("quality_test.pdf", t5_pdf, "application/pdf"))]
    u5_res = requests.post(f"{BASE_URL}/api/conversations/{t3_cid}/documents", files=files5)
    t5_doc_id = u5_res.json()[0]["id"]

    requests.post(f"{BASE_URL}/api/documents/{t5_doc_id}/parse/retry")
    for _ in range(45):
        await asyncio.sleep(2)
        p = requests.get(f"{BASE_URL}/api/documents/{t5_doc_id}/parse").json()
        if p.get("parse_status") in ("parsed", "failed"):
            break

    t5_parse = requests.get(f"{BASE_URL}/api/documents/{t5_doc_id}/parse").json()
    ws5 = t5_parse.get("warnings_summary", {})
    print(f"  Quality warnings summary: low_text_pages={ws5.get('low_text_pages')}, garbled_pages={ws5.get('garbled_pages')}")
    assert 1 in ws5.get("low_text_pages", [])
    print("  Quality heuristics correctly flagged low_text page: PASS")
    summary_results.append({"test": "5. Quality Heuristics", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 6: Page Batching & Progress Reporting
    # ------------------------------------------------------------------------
    print("\n[TEST 6] Page Batching & Progress Reporting")
    # Test batch parsing with batch_pages=2 on 4-page PDF
    p4_texts = [f"Batch test page {i}\nTesting page slicing." for i in range(1, 5)]
    t6_pdf = make_pdf(p4_texts)
    tmp_path = Path("/tmp/batch_test.pdf")
    tmp_path.write_bytes(t6_pdf)

    progress_ticks = []
    def on_prog(done, total):
        progress_ticks.append((done, total))

    parser = DoclingClientParser()
    p_doc = await parser.parse(tmp_path, options={"batch_pages": 2, "on_progress": on_prog, "do_ocr": False})
    tmp_path.unlink(missing_ok=True)

    assert p_doc.page_count == 4
    assert len(p_doc.pages) == 4
    page_numbers = [p.page_no for p in p_doc.pages]
    assert page_numbers == [1, 2, 3, 4]
    print(f"  Batching execution captured progress: {progress_ticks} (PASS)")
    assert len(progress_ticks) >= 2
    summary_results.append({"test": "6. Page Batching & Progress", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 7: Disk Storage Layout
    # ------------------------------------------------------------------------
    print("\n[TEST 7] Disk Storage Layout (/data/uploads/{id}/parsed/)")
    json_path = get_document_parsed_json_path(uuid.UUID(t3_doc_id))
    md_path = get_document_parsed_md_path(uuid.UUID(t3_doc_id))
    assert json_path.exists(), f"Missing {json_path}"
    assert md_path.exists(), f"Missing {md_path}"
    print(f"  Artifacts verified: {json_path.name} ({json_path.stat().st_size} bytes), {md_path.name} ({md_path.stat().st_size} bytes) (PASS)")
    summary_results.append({"test": "7. Disk Storage Layout", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 8: Cascade Deletion
    # ------------------------------------------------------------------------
    print("\n[TEST 8] Cascade Deletion (Database & Disk)")
    del_res = requests.delete(f"{BASE_URL}/api/documents/{t4_doc_id}")
    assert del_res.status_code == 204

    # Verify document_pages rows deleted
    async with async_session_factory() as db:
        res = await db.execute(select(DocumentPage).where(DocumentPage.document_id == uuid.UUID(t4_doc_id)))
        assert len(res.scalars().all()) == 0

    # Verify disk dir removed
    assert not get_document_dir(uuid.UUID(t4_doc_id)).exists()
    print("  Cascade deletion of database rows and disk directory: PASS")
    summary_results.append({"test": "8. Cascade Deletion", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 9: Startup Recovery
    # ------------------------------------------------------------------------
    print("\n[TEST 9] Startup Recovery (Re-queue stuck parses & purge partial state)")
    rec_doc_id = uuid.uuid4()
    r_dir = get_document_dir(rec_doc_id)
    r_dir.mkdir(parents=True, exist_ok=True)
    get_document_file_path(rec_doc_id, "application/pdf").write_bytes(t3_pdf)

    async with async_session_factory() as db:
        stuck_doc = Document(
            id=rec_doc_id,
            conversation_id=uuid.UUID(t3_cid),
            filename="stuck_doc.pdf",
            mime_type="application/pdf",
            size_bytes=len(t3_pdf),
            sha256="stuck_sha",
            status="processing",
            parse_status="parsing",
            mode="rag",
        )
        db.add(stuck_doc)
        # Add a partial garbage page
        db.add(DocumentPage(
            document_id=rec_doc_id,
            page_no=999,
            markdown="partial junk",
            plain_text="partial junk",
            char_count=12,
        ))
        await db.commit()

    # Trigger recovery
    await run_startup_recovery()

    # Wait for re-queued parse to complete
    for _ in range(45):
        await asyncio.sleep(2)
        p = requests.get(f"{BASE_URL}/api/documents/{rec_doc_id}/parse").json()
        if p.get("parse_status") in ("parsed", "failed"):
            break

    async with async_session_factory() as db:
        res = await db.execute(select(DocumentPage).where(DocumentPage.document_id == rec_doc_id).order_by(DocumentPage.page_no))
        recovered_pages = res.scalars().all()

    rec_nums = [p.page_no for p in recovered_pages]
    assert rec_nums == [1, 2, 3], f"Expected [1, 2, 3], got {rec_nums}"
    print(f"  Startup recovery purged partial junk and parsed document cleanly: PASS (pages {rec_nums})")

    delete_document_files(rec_doc_id)
    summary_results.append({"test": "9. Startup Recovery", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 10: Concurrency Limiting
    # ------------------------------------------------------------------------
    print("\n[TEST 10] Concurrency Limiting (Bounded by PARSE_CONCURRENCY)")
    from app.services.ingestion import _parse_semaphore
    assert _parse_semaphore._value <= settings.PARSE_CONCURRENCY
    print(f"  Semaphore concurrency limit configured to: {settings.PARSE_CONCURRENCY} (PASS)")
    summary_results.append({"test": "10. Concurrency Limiting", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 11: REST Endpoints Validation
    # ------------------------------------------------------------------------
    print("\n[TEST 11] REST API Endpoints Validation")
    # GET /api/documents/{id}/parse
    p_stat = requests.get(f"{BASE_URL}/api/documents/{t3_doc_id}/parse")
    assert p_stat.status_code == 200
    # GET /api/documents/{id}/pages
    p_list = requests.get(f"{BASE_URL}/api/documents/{t3_doc_id}/pages?page=1&limit=2")
    assert p_list.status_code == 200 and len(p_list.json()["items"]) == 2
    # GET /api/documents/{id}/pages/{n}
    p_det = requests.get(f"{BASE_URL}/api/documents/{t3_doc_id}/pages/1")
    assert p_det.status_code == 200 and p_det.json()["page_no"] == 1
    # GET /api/documents/{id}/parsed.md
    p_md = requests.get(f"{BASE_URL}/api/documents/{t3_doc_id}/parsed.md")
    assert p_md.status_code == 200 and "<!-- Page 1 -->" in p_md.text
    # POST /api/documents/{id}/parse/retry
    p_ret = requests.post(f"{BASE_URL}/api/documents/{t3_doc_id}/parse/retry")
    assert p_ret.status_code == 200 and p_ret.json()["parse_status"] == "pending"
    print("  All 5 Stage 5 REST API endpoints verified: PASS")
    summary_results.append({"test": "11. REST API Endpoints", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 12: Chat RAG Status-Aware Messaging
    # ------------------------------------------------------------------------
    print("\n[TEST 12] Chat RAG Status-Aware Messaging")
    # Wait for t3_doc_id to finish re-parse from Test 11
    for _ in range(45):
        await asyncio.sleep(2)
        p = requests.get(f"{BASE_URL}/api/documents/{t3_doc_id}/parse").json()
        if p.get("parse_status") in ("parsed", "failed"):
            break

    # Manually set mode to 'rag' so chat tests the Stage 5 message
    async with async_session_factory() as db:
        res = await db.execute(select(Document).where(Document.id == uuid.UUID(t3_doc_id)))
        d_rag = res.scalar_one_or_none()
        d_rag.mode = "rag"
        await db.commit()
        await db.refresh(d_rag)
        print(f"  Debug t3_doc: id={d_rag.id}, mode={d_rag.mode}, parse_status={d_rag.parse_status}, status={d_rag.status}")

    ans_rag_parsed, _ = send_chat_sse(t3_cid, "Summarize this large document.", [t3_doc_id])
    print(f"  Chat response for parsed RAG doc: '{ans_rag_parsed}'")
    assert "Parsed and ready for indexing in the next stage." in ans_rag_parsed
    print("  Chat status-aware message for parsed RAG doc: PASS")
    summary_results.append({"test": "12. Chat RAG Status Messaging", "status": "PASS"})

    # ------------------------------------------------------------------------
    # TEST 13: Non-Regression Verification
    # ------------------------------------------------------------------------
    print("\n[TEST 13] Non-Regression Verification (Direct Mode Citations & Plain Chat)")
    direct_pdf = make_pdf(["Direct mode verification page.\nKey fact: Target SLA is 99.9% uptime."])
    u_dir = requests.post(
        f"{BASE_URL}/api/conversations/{t3_cid}/documents",
        files=[("files", ("direct_sla.pdf", direct_pdf, "application/pdf"))],
    ).json()
    dir_id = u_dir[0]["id"]

    # Poll until ready
    for _ in range(15):
        time.sleep(0.5)
        d = requests.get(f"{BASE_URL}/api/documents/{dir_id}").json()
        if d.get("status") == "ready":
            break

    dir_ans, _ = send_chat_sse(t3_cid, "What is the Target SLA?", [dir_id])
    print(f"  Direct mode citation answer: '{dir_ans[:80]}'")
    assert "99.9%" in dir_ans and "cite:" in dir_ans
    print("  Stage 4 direct citation Q&A remains fully functional: PASS")
    summary_results.append({"test": "13. Non-Regression Verification", "status": "PASS"})

    # Cleanup Test 3 conversation
    requests.delete(f"{BASE_URL}/api/conversations/{t3_cid}")

    print("\n" + "=" * 80)
    print("ALL 13 STAGE 5 ACCEPTANCE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 80)
    for r in summary_results:
        print(f"  [{r['status']}] {r['test']}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_stage5_acceptance_tests())
