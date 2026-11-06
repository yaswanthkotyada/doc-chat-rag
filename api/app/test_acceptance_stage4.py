"""
Stage 4 Acceptance Test Suite (Milestone 6)
Executes all 14 acceptance tests defined in the Stage 4 Direct Mode specification.
"""
import asyncio
from datetime import datetime, timezone
import io
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter
import pypdf
import requests
from sqlalchemy import select, update

from app.config import settings
from app.db import async_session_factory
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.services.citations import parse_and_validate_citations
from app.services.llm import (
    GeminiLLMService,
    LLMConfigurationError,
    LLMError,
    llm_service,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
logger = logging.getLogger("acceptance_stage4")


def make_pdf(pages_text: List[str]) -> bytes:
    """Generate a multi-page PDF with selectable text using valid PDF 1.4 syntax."""
    font_obj_idx = 3
    num_pages = len(pages_text)
    page_objs = []
    content_objs = []
    curr_idx = 4
    for _ in range(num_pages):
        page_objs.append(curr_idx)
        content_objs.append(curr_idx + 1)
        curr_idx += 2

    kids_str = " ".join(f"{idx} 0 R" for idx in page_objs)
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages = f"<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>".encode("ascii")
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    objs = [catalog, pages, font]
    for i, text in enumerate(pages_text):
        clean_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines = clean_text.split("\n")
        stream_cmds = ["BT", "/F1 14 Tf", "50 720 Td", "20 TL"]
        for idx, line in enumerate(lines):
            if idx > 0:
                stream_cmds.append(f"T* ({line}) Tj")
            else:
                stream_cmds.append(f"({line}) Tj")
        stream_cmds.append("ET")
        stream_data = "\n".join(stream_cmds).encode("latin1")
        content_stream = (
            f"<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
            + stream_data
            + b"\nendstream"
        )
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_objs[i]} 0 R "
            f"/Resources << /Font << /F1 {font_obj_idx} 0 R >> >> >>".encode("ascii")
        )
        objs.append(page_obj)
        objs.append(content_stream)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj_bytes in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode("ascii"))
        out.write(obj_bytes)
        out.write(b"\nendobj\n")
    xref_offset = out.tell()
    out.write(b"xref\n")
    out.write(f"0 {len(objs) + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(b"trailer\n")
    out.write(f"<< /Size {len(objs) + 1} /Root 1 0 R >>\n".encode("ascii"))
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n".encode("ascii"))
    out.write(b"%%EOF\n")
    return out.getvalue()


def make_image(text_lines: List[str], blur_radius: int = 0) -> bytes:
    """Generate a PNG image with rendered text and optional Gaussian blur."""
    img = Image.new("RGB", (650, 320), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 30
    for line in text_lines:
        draw.text((30, y), line, fill=(0, 0, 0))
        y += 35
    if blur_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def send_chat_sse(
    conversation_id: str,
    message: str,
    document_ids: Optional[List[str]] = None,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """
    Sends chat request and collects streamed tokens, done payload, or error.
    Returns (answer_text, done_data, error_msg).
    """
    payload: Dict[str, Any] = {
        "conversation_id": conversation_id,
        "message": message,
    }
    if document_ids is not None:
        payload["document_ids"] = document_ids

    res = requests.post(f"{BASE_URL}/api/chat", json=payload, stream=True)
    if res.status_code != 200:
        return "", None, f"HTTP {res.status_code}: {res.text}"

    tokens = []
    done_data = None
    error_msg = None
    prev_event = ""

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
    return answer_text, done_data, error_msg


def upload_test_doc(
    conversation_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
) -> Dict[str, Any]:
    """Uploads a document and polls until status is 'ready'."""
    res = requests.post(
        f"{BASE_URL}/api/conversations/{conversation_id}/documents",
        files=[("files", (filename, content, mime_type))],
    )
    assert res.status_code == 201, f"Upload failed: {res.text}"
    doc_id = res.json()[0]["id"]

    for _ in range(20):
        time.sleep(0.5)
        d = requests.get(f"{BASE_URL}/api/documents/{doc_id}").json()
        if d.get("status") == "ready":
            return d
    raise TimeoutError(f"Document {doc_id} did not become ready.")


# ============================================================================
# 14 ACCEPTANCE TESTS (ASYNC RUNNER)
# ============================================================================

async def run_all_acceptance_tests():
    print("=" * 80)
    print("STAGE 4 DIRECT MODE: COMPREHENSIVE ACCEPTANCE TEST SUITE")
    print(f"Base URL: {BASE_URL}")
    print(f"Target Model: {settings.GEMINI_MODEL}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    results_summary: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------------
    # Test 1: Migrations
    # ------------------------------------------------------------------------
    print("\n[TEST 1] Alembic Migrations Apply Cleanly & Are Re-Runnable")
    try:
        res = subprocess.run(
            ["alembic", "current"],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"  Alembic current output: {res.stdout.strip()}")
        assert "head" in res.stdout, "Alembic not at head"

        res_up = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True,
        )
        print("  Alembic upgrade head re-ran cleanly without error.")
        results_summary.append({"test": "1. Migrations", "status": "PASS", "details": "Alembic at head & re-runnable"})
    except Exception as e:
        results_summary.append({"test": "1. Migrations", "status": "FAIL", "details": str(e)})
        print(f"  Test 1 Failed: {e}")

    # ------------------------------------------------------------------------
    # Test 2: 5-Page Text PDF with Distinct Facts & Page Citations
    # ------------------------------------------------------------------------
    print("\n[TEST 2] 5-Page Text PDF with Distinct Facts on Different Pages")
    p1 = "Project Titan-Solar Architecture Overview.\nKickoff Date: March 15, 2024.\nSponsor Organization: Orion Aerospace Ventures."
    p2 = "Lead System Architect: Dr. Elena Rostova.\nPrimary Database: PostgreSQL 16 with pgvector extension.\nBroker: Redis 7 Cluster."
    p3 = "Phase 1 Allocated Budget: $450,000 USD.\nHardware and Cloud Equipment Cap: $80,000 USD.\nContingency Allocation: $25,000 USD."
    p4 = "Primary Production Data Center: Frankfurt, Germany (Region EU-Central-1).\nDisaster Recovery Hot Standby: Dublin, Ireland.\nTarget RPO: 5 minutes, RTO: 15 minutes."
    p5 = "Security Compliance Standard: SOC2 Type II Certification.\nAnnual Audit Renewal Window: December 2025.\nData Retention Requirement: 7 years encrypted at rest."

    pdf_bytes = make_pdf([p1, p2, p3, p4, p5])
    conv2 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 2 PDF"}).json()
    cid2 = conv2["id"]
    doc2 = upload_test_doc(cid2, "titan_spec.pdf", pdf_bytes, "application/pdf")
    print(f"  Uploaded titan_spec.pdf: id={doc2['id']}, pages={doc2['page_count']}, mode={doc2['mode']}")
    assert doc2["mode"] == "direct"
    assert doc2["page_count"] == 5

    q2_cases = [
        {
            "q": "What is the Phase 1 allocated budget and hardware equipment cap?",
            "expected_page": 3,
            "expected_kw": ["$450,000", "$80,000"],
        },
        {
            "q": "Who is the lead system architect and which database is selected?",
            "expected_page": 2,
            "expected_kw": ["Elena Rostova", "PostgreSQL"],
        },
        {
            "q": "What security compliance standard was achieved and when is the audit renewal?",
            "expected_page": 5,
            "expected_kw": ["SOC2", "December 2025"],
        },
    ]

    t2_pass = True
    t2_records = []
    for item in q2_cases:
        ans, done, err = send_chat_sse(cid2, item["q"], [doc2["id"]])
        if err:
            print(f"  Chat SSE Error: {err}")
        citations = (done or {}).get("citations", [])
        cited_pages = [c.get("page") for c in citations if c.get("filename") == "titan_spec.pdf"]
        has_kw = any(k.lower() in ans.lower() for k in item["expected_kw"])
        page_correct = (item["expected_page"] in cited_pages)

        record = {
            "question": item["q"],
            "answer": ans[:140] + ("..." if len(ans) > 140 else ""),
            "citations": citations,
            "expected_page": item["expected_page"],
            "cited_pages": cited_pages,
            "page_correct": page_correct,
            "content_correct": has_kw,
        }
        t2_records.append(record)
        print(f"  Q: {item['q']}")
        print(f"  Answer: {record['answer']}")
        print(f"  Citations: {citations} -> Cited Page(s): {cited_pages} (Expected: {item['expected_page']}) -> Match: {page_correct}")
        if not (page_correct and has_kw):
            t2_pass = False

    results_summary.append({
        "test": "2. 5-Page PDF Citations",
        "status": "PASS" if t2_pass else "PARTIAL",
        "details": t2_records,
    })

    # ------------------------------------------------------------------------
    # Test 3: PDF with Table
    # ------------------------------------------------------------------------
    print("\n[TEST 3] PDF with Financial / Operational Table")
    table_content = (
        "Quarterly Financial and Operational Performance Report 2024\n"
        "-------------------------------------------------------------------\n"
        "Quarter | Revenue ($M) | Operating Expenses ($M) | Net Profit ($M)\n"
        "-------------------------------------------------------------------\n"
        "Q1 2024 | 12.5         | 8.2                      | 4.3\n"
        "Q2 2024 | 14.8         | 9.1                      | 5.7\n"
        "Q3 2024 | 16.2         | 9.8                      | 6.4\n"
        "Q4 2024 | 19.0         | 10.5                     | 8.5\n"
        "-------------------------------------------------------------------\n"
        "Fiscal Year 2024 Total Net Profit: $24.9M\n"
    )
    table_pdf_bytes = make_pdf([table_content])
    conv3 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 3 Table"}).json()
    cid3 = conv3["id"]
    doc3 = upload_test_doc(cid3, "quarterly_financials.pdf", table_pdf_bytes, "application/pdf")
    ans3, done3, err3 = send_chat_sse(
        cid3,
        "Based on the quarterly performance table, what were the Operating Expenses and Net Profit in Q3 2024?",
        [doc3["id"]],
    )
    if err3:
        print(f"  Chat SSE Error: {err3}")
    citations3 = (done3 or {}).get("citations", [])
    print(f"  Table Answer: {ans3}")
    print(f"  Table Citations: {citations3}")
    t3_pass = ("9.8" in ans3) and ("6.4" in ans3)
    results_summary.append({
        "test": "3. PDF Table Reading",
        "status": "PASS" if t3_pass else "FAIL",
        "details": {"answer": ans3, "citations": citations3},
    })

    # ------------------------------------------------------------------------
    # Test 4: Image Invoice & Blurry Image Refusal
    # ------------------------------------------------------------------------
    print("\n[TEST 4] Image Input: Clean Invoice Extraction & Blurry Image Handling")
    conv4 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 4 Images"}).json()
    cid4 = conv4["id"]

    # 4A. Clean Invoice
    inv_bytes = make_image([
        "INVOICE #INV-2024-8841",
        "Vendor: Acme Cloud Services Inc.",
        "Billing Period: October 2024",
        "Due Date: November 28, 2024",
        "Total Amount Due: $1,420.50 USD",
    ], blur_radius=0)
    doc4a = upload_test_doc(cid4, "invoice_8841.png", inv_bytes, "image/png")
    ans4a, done4a, err4a = send_chat_sse(cid4, "What is the invoice number and the total amount due?", [doc4a["id"]])
    if err4a:
        print(f"  Chat SSE Error: {err4a}")
    print(f"  Clean Invoice Answer: {ans4a}")
    t4a_pass = ("8841" in ans4a) and ("1,420.50" in ans4a or "1420.50" in ans4a)

    # 4B. Blurry Image
    blurry_bytes = make_image([
        "Secret Code: 994821",
        "PIN: 7712",
        "Authorized Signature: J. Doe",
    ], blur_radius=22)
    doc4b = upload_test_doc(cid4, "blurry_receipt.png", blurry_bytes, "image/png")
    ans4b, done4b, err4b = send_chat_sse(cid4, "What is the Secret Code and PIN shown on this receipt?", [doc4b["id"]])
    if err4b:
        print(f"  Chat SSE Error: {err4b}")
    print(f"  Blurry Image Answer: {ans4b}")
    refusal_keywords = ["blur", "unreadable", "illegible", "cannot read", "cannot be read", "cannot make out", "clear"]
    t4b_pass = any(kw in ans4b.lower() for kw in refusal_keywords) and ("994821" not in ans4b)

    results_summary.append({
        "test": "4. Image & Blurry Handling",
        "status": "PASS" if (t4a_pass and t4b_pass) else "PARTIAL",
        "details": {
            "invoice_answer": ans4a,
            "invoice_correct": t4a_pass,
            "blurry_answer": ans4b,
            "blurry_refused": t4b_pass,
        },
    })

    # ------------------------------------------------------------------------
    # Test 5: Question Not in Documents
    # ------------------------------------------------------------------------
    print("\n[TEST 5] Unanswerable Question (Answer Not in Documents)")
    ans5, done5, err5 = send_chat_sse(
        cid2,
        "What is Dr. Elena Rostova's favorite dessert and what year did she graduate high school?",
        [doc2["id"]],
    )
    if err5:
        print(f"  Chat SSE Error: {err5}")
    print(f"  Answer: {ans5}")
    not_found_kws = [
        "not mention",
        "not provided",
        "not found",
        "does not contain",
        "do not contain",
        "no information",
        "not state",
    ]
    t5_pass = any(kw in ans5.lower() for kw in not_found_kws)
    results_summary.append({
        "test": "5. Out of Context Question",
        "status": "PASS" if t5_pass else "FAIL",
        "details": {"answer": ans5},
    })

    # ------------------------------------------------------------------------
    # Test 6: Cross-Document Comparison (Two Files Attached)
    # ------------------------------------------------------------------------
    print("\n[TEST 6] Cross-Document Comparison with Multi-File Citations")
    conv6 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 6 Comparison"}).json()
    cid6 = conv6["id"]

    v1_text = b"System Spec v1.0:\nLatency SLA: 250 milliseconds.\nMax Concurrency: 500 active users.\nStorage Quota: 50 GB per tenant.\n"
    v2_text = b"System Spec v2.0:\nLatency SLA: 100 milliseconds.\nMax Concurrency: 2500 active users.\nStorage Quota: 250 GB per tenant.\n"

    doc6a = upload_test_doc(cid6, "spec_v1.txt", v1_text, "text/plain")
    doc6b = upload_test_doc(cid6, "spec_v2.txt", v2_text, "text/plain")

    ans6, done6, err6 = send_chat_sse(
        cid6,
        "Compare the Latency SLA and Max Concurrency between Specification v1.0 and Specification v2.0.",
        [doc6a["id"], doc6b["id"]],
    )
    if err6:
        print(f"  Chat SSE Error: {err6}")
    citations6 = (done6 or {}).get("citations", [])
    cited_files = set(c.get("filename") for c in citations6)
    print(f"  Comparison Answer: {ans6}")
    print(f"  Cited Files: {cited_files}")
    t6_pass = ("spec_v1.txt" in cited_files and "spec_v2.txt" in cited_files) and ("250" in ans6 and "100" in ans6)
    results_summary.append({
        "test": "6. Cross-Document Citations",
        "status": "PASS" if t6_pass else "FAIL",
        "details": {"answer": ans6, "cited_files": list(cited_files)},
    })

    # ------------------------------------------------------------------------
    # Test 7: Document Selection Toggle (Deselect One File)
    # ------------------------------------------------------------------------
    print("\n[TEST 7] Deselect One Document via Selection Toggle")
    ans7, done7, err7 = send_chat_sse(
        cid6,
        "What is the Latency SLA and Storage Quota for the system?",
        [doc6a["id"]],  # Only spec_v1.txt attached
    )
    if err7:
        print(f"  Chat SSE Error: {err7}")
    citations7 = (done7 or {}).get("citations", [])
    cited_files7 = set(c.get("filename") for c in citations7)
    print(f"  Single Document Answer: {ans7}")
    print(f"  Single Document Citations: {cited_files7}")
    t7_pass = ("spec_v1.txt" in cited_files7) and ("spec_v2.txt" not in cited_files7) and ("250" in ans7) and ("2500" not in ans7)
    results_summary.append({
        "test": "7. Document Selection Toggle",
        "status": "PASS" if t7_pass else "FAIL",
        "details": {"cited_files": list(cited_files7), "v2_excluded": "spec_v2.txt" not in cited_files7},
    })

    # ------------------------------------------------------------------------
    # Test 8: Citation Parser Unit Tests & Malformed Marker Rejection
    # ------------------------------------------------------------------------
    print("\n[TEST 8] Citation Parser Unit Tests & Malformed Marker Filtering")
    dummy_doc1 = Document(id="d1", filename="contract.pdf", page_count=5)
    dummy_doc2 = Document(id="d2", filename="notes.txt", page_count=None)

    raw_test_text = (
        "The vendor agreement is valid [[cite: contract.pdf | p.2]]. "
        "The fake document was also cited [[cite: non_existent.pdf | p.1]]. "
        "The page number is too high [[cite: contract.pdf | p.99]]. "
        "Text notes should not have pages [[cite: notes.txt | p.4]]."
    )
    cleaned, c_list = parse_and_validate_citations(raw_test_text, [dummy_doc1, dummy_doc2])
    print(f"  Cleaned text: {cleaned}")
    print(f"  Validated citations: {c_list}")

    t8_pass = (
        len(c_list) == 3  # non_existent.pdf dropped completely
        and any(c["filename"] == "contract.pdf" and c["page"] == 2 for c in c_list)
        and any(c["filename"] == "contract.pdf" and c["page"] is None for c in c_list)  # p.99 stripped
        and any(c["filename"] == "notes.txt" and c["page"] is None for c in c_list)  # notes.txt page stripped
    )
    results_summary.append({
        "test": "8. Citation Parser & Filtering",
        "status": "PASS" if t8_pass else "FAIL",
        "details": {"c_list": c_list},
    })

    # ------------------------------------------------------------------------
    # Test 9: Gemini Files API Expiry & Transparent Re-Upload
    # ------------------------------------------------------------------------
    print("\n[TEST 9] Gemini File Expiry: Transparent Re-upload & Answer Continuity")
    async with async_session_factory() as db:
        res_d = await db.execute(select(Document).where(Document.id == doc2["id"]))
        d_obj = res_d.scalar_one()
        old_meta = dict(d_obj.meta or {})
        past_time = "2020-01-01T00:00:00Z"
        old_meta["gemini_file_expires_at"] = past_time
        await db.execute(
            update(Document).where(Document.id == doc2["id"]).values(meta=old_meta)
        )
        await db.commit()
        print(f"  Mutated gemini_file_expires_at to past: {past_time}")

    ans9, done9, err9 = send_chat_sse(cid2, "What is the primary database selected?", [doc2["id"]])
    if err9:
        print(f"  Chat SSE Error: {err9}")
    print(f"  Re-upload Answer: {ans9}")

    async with async_session_factory() as db:
        res_d = await db.execute(select(Document).where(Document.id == doc2["id"]))
        d_obj = res_d.scalar_one()
        new_meta = dict(d_obj.meta or {})
        new_expires_val = new_meta.get("gemini_file_expires_at")
        print(f"  Updated gemini_file_expires_at in DB: {new_expires_val}")

    t9_pass = ("PostgreSQL" in ans9) and (new_expires_val and new_expires_val > "2026-01-01")
    results_summary.append({
        "test": "9. Files API Expiry & Re-upload",
        "status": "PASS" if t9_pass else "FAIL",
        "details": {"new_expires": new_expires_val, "answer_success": "PostgreSQL" in ans9},
    })

    # ------------------------------------------------------------------------
    # Test 10: PDF Over DIRECT_MAX_PAGES -> mode = 'rag' & Warning Message
    # ------------------------------------------------------------------------
    print("\n[TEST 10] PDF over DIRECT_MAX_PAGES -> mode = 'rag' & Warning Message")
    w = pypdf.PdfWriter()
    for _ in range(45):
        w.add_blank_page(width=100, height=100)
    rag_buf = io.BytesIO()
    w.write(rag_buf)
    rag_pdf_bytes = rag_buf.getvalue()

    conv10 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Test 10 RAG"}).json()
    cid10 = conv10["id"]
    doc10 = upload_test_doc(cid10, "oversized_manual.pdf", rag_pdf_bytes, "application/pdf")
    print(f"  Oversized manual: pages={doc10['page_count']}, mode={doc10['mode']}")
    assert doc10["mode"] == "rag"

    ans10, done10, _ = send_chat_sse(cid10, "Summarize page 1.", [doc10["id"]])
    print(f"  RAG Warning Streamed: {ans10}")
    t10_pass = "too large for direct mode" in ans10
    results_summary.append({
        "test": "10. RAG Document Warning",
        "status": "PASS" if t10_pass else "FAIL",
        "details": {"warning_message": ans10},
    })

    # ------------------------------------------------------------------------
    # Test 11: Token Limit Exceeded
    # ------------------------------------------------------------------------
    print("\n[TEST 11] Exceed DIRECT_MAX_TOTAL_TOKENS: Clear Error Naming Documents")
    from google.genai import types
    service = GeminiLLMService()
    orig_limit = settings.DIRECT_MAX_TOTAL_TOKENS
    settings.DIRECT_MAX_TOTAL_TOKENS = 5  # Set a very low limit to ensure trigger
    captured_limit_err = None
    try:
        sample_messages = [
            {"role": "user", "content": "Please analyze this large attached dataset and document comprehensively in great detail."}
        ]
        sample_parts = [
            types.Part.from_text(
                text="Document: dataset_large.csv (CSV, 500 rows)\n---\nRow 1, Value A, Value B, Value C\nRow 2, Value D, Value E, Value F\n---"
            )
        ]
        try:
            gen = service.stream_chat(
                system_instruction="Be helpful.",
                messages=sample_messages,
                attached_parts=sample_parts,
                attached_doc_names=["dataset_large.csv", "contract.pdf"],
            )
            async for _ in gen:
                pass
        except LLMError as le:
            captured_limit_err = str(le)
    finally:
        settings.DIRECT_MAX_TOTAL_TOKENS = orig_limit

    print(f"  Captured Token Limit Error: {captured_limit_err}")
    t11_pass = (
        captured_limit_err is not None
        and "exceeds token limit" in captured_limit_err
        and "dataset_large.csv" in captured_limit_err
        and "contract.pdf" in captured_limit_err
    )
    results_summary.append({
        "test": "11. Token Limit Naming Documents",
        "status": "PASS" if t11_pass else "FAIL",
        "details": {"error_message": captured_limit_err},
    })

    # ------------------------------------------------------------------------
    # Test 12: Invalid GEMINI_API_KEY Security Verification
    # ------------------------------------------------------------------------
    print("\n[TEST 12] Wrong GEMINI_API_KEY: Clean Error & No Secret Leaks")
    fake_bad_key = "AIzaSyFakeSecretKey_9988776655"
    service_bad = GeminiLLMService(api_key=fake_bad_key)
    try:
        gen = service_bad.stream_chat(
            system_instruction="Be helpful.",
            messages=[{"role": "user", "content": "Hello"}],
        )
        async for _ in gen:
            pass
        t12_pass, t12_detail = False, "Expected error but call succeeded"
    except (LLMConfigurationError, LLMError) as e:
        err_str = str(e)
        leaks_key = fake_bad_key in err_str
        leaks_uri = "https://generativelanguage.googleapis.com" in err_str
        print(f"  Caught clean error: {err_str}")
        print(f"  Key leaked: {leaks_key}, URI leaked: {leaks_uri}")
        t12_pass, t12_detail = (not leaks_key and not leaks_uri), err_str
    except Exception as e:
        t12_pass, t12_detail = False, f"Unexpected exception: {e}"

    results_summary.append({
        "test": "12. Invalid Key & Leak Prevention",
        "status": "PASS" if t12_pass else "FAIL",
        "details": {"leak_free": t12_pass, "error_text": t12_detail},
    })

    # ------------------------------------------------------------------------
    # Test 13: Regression Checks (Stage 2 Chat, Stage 3 Document CRUD, Health)
    # ------------------------------------------------------------------------
    print("\n[TEST 13] Regressions: Stage 2 Plain Chat, Stage 3 Document CRUD, /api/health")
    h_res = requests.get(f"{BASE_URL}/api/health")
    health_ok = (h_res.status_code == 200 and h_res.json().get("api") == "ok")

    conv13 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Regression Chat"}).json()
    cid13 = conv13["id"]
    ans13, done13, _ = send_chat_sse(cid13, "Reply with 'Regression Stage 2 Passed'.")
    plain_chat_ok = "Regression Stage 2 Passed" in ans13 or len(ans13) > 5

    crud_doc = upload_test_doc(cid13, "to_delete.txt", b"temporary data", "text/plain")
    del_res = requests.delete(f"{BASE_URL}/api/documents/{crud_doc['id']}")
    doc_crud_ok = (del_res.status_code == 204)

    t13_pass = health_ok and plain_chat_ok and doc_crud_ok
    print(f"  Health: {health_ok}, Plain Chat: {plain_chat_ok}, Document Delete: {doc_crud_ok}")
    results_summary.append({
        "test": "13. Regressions",
        "status": "PASS" if t13_pass else "FAIL",
        "details": {
            "health_ok": health_ok,
            "plain_chat_ok": plain_chat_ok,
            "doc_crud_ok": doc_crud_ok,
        },
    })

    # ------------------------------------------------------------------------
    # Test 14: Written Assessment of Page Citation Reliability
    # ------------------------------------------------------------------------
    print("\n[TEST 14] Citation Reliability Assessment Compilation")
    correct_citations = sum(1 for r in t2_records if r["page_correct"])
    total_citations = len(t2_records)
    accuracy_pct = (correct_citations / total_citations * 100) if total_citations else 0
    print(f"  Empirical Citation Accuracy in 5-Page Test: {correct_citations} / {total_citations} ({accuracy_pct:.1f}%)")

    results_summary.append({
        "test": "14. Citation Reliability Assessment",
        "status": "RECORDED",
        "details": {
            "test2_accuracy": f"{correct_citations}/{total_citations}",
            "table_cited": len(citations3) > 0,
            "multi_file_cited": len(citations6) == 2,
        },
    })

    print("\n" + "=" * 80)
    print("ALL 14 ACCEPTANCE TESTS COMPLETED")
    print("=" * 80)
    for r in results_summary:
        print(f"[{r['status']}] {r['test']}")

    return results_summary


if __name__ == "__main__":
    asyncio.run(run_all_acceptance_tests())
