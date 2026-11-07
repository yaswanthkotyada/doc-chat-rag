"""
Stage 7 Direct vs RAG Evaluation Script: run_direct_vs_rag.py

Evaluates 10 realistic questions across 4 categories against the same document:
1. Factual lookup (specific dates, numbers)
2. Multi-hop / across sections (synthesizing info from different pages)
3. Table extraction (specific rows/cells from financial tables)
4. Absent information / Negative testing (facts not in the document)

Compares:
- Direct Mode (Stage 4) vs RAG Mode (Stage 7 with tool-calling loop)
- Answer Correctness
- Page Citations Accuracy
- Latency (seconds)
- Token Consumption
"""

import asyncio
import io
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Tuple
import requests

from app.db import async_session_factory, engine
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.services.ingestion import parse_document_task, index_document_task

BASE_URL = os.environ.get("API_URL", "http://localhost:8000")
logger = logging.getLogger("eval_direct_vs_rag")


def make_pdf(pages_text: List[str]) -> bytes:
    """Generate a multi-page PDF with valid PDF 1.4 syntax."""
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
        stream_cmds = ["BT", "/F1 12 Tf", "40 730 Td", "16 TL"]
        for idx, line in enumerate(lines):
            if idx > 0:
                stream_cmds.append("T*")
            stream_cmds.append(f"({line}) Tj")
        stream_cmds.append("ET")
        stream_bytes = "\n".join(stream_cmds).encode("latin-1", errors="replace")
        content_obj = f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream"

        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_objs[i]} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode("ascii")
        objs.extend([page_obj, content_obj])

    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objs, start=1):
        offsets.append(len(body))
        body.extend(f"{idx} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")

    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    trailer = f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii")
    body.extend(trailer)
    return bytes(body)


def create_evaluation_document() -> bytes:
    """Creates a 6-page realistic corporate report with text, tables, and architecture details."""
    p1 = (
        "NEXUS CORP ANNUAL OPERATIONS & TECHNOLOGY REPORT 2024\n"
        "Executive Summary and Corporate Overview\n"
        "Nexus Corporation delivered record operating performance across all enterprise software business units in 2024.\n"
        "Total company revenue reached $84.5 million, representing a 28% year-over-year expansion.\n"
        "Corporate Leadership: Dr. Aris Vance serves as Chief Executive Officer, and Elena Rostova serves as Chief Financial Officer.\n"
        "Headquarters: Nexus Tower, 500 Technology Square, Cambridge, Massachusetts.\n"
        "Our core mission is delivering mission-critical cloud infrastructure and autonomous AI operations."
    )

    p2 = (
        "SECTION 2: FINANCIAL PERFORMANCE & REVENUE BREAKDOWN\n"
        "Quarterly Financial and Operational Metrics Table (FY 2024):\n"
        "Quarter | Revenue ($M) | Operating Expenses ($M) | R&D Spend ($M) | Net Profit ($M)\n"
        "Q1 2024 | 18.2         | 11.4                    | 4.2            | 6.8\n"
        "Q2 2024 | 20.5         | 12.1                    | 4.8            | 8.4\n"
        "Q3 2024 | 22.1         | 13.0                    | 5.1            | 9.1\n"
        "Q4 2024 | 23.7         | 13.5                    | 5.4            | 10.2\n"
        "Total FY2024 Net Profit across all four quarters is $34.5M.\n"
        "Gross margin remained steady at 78.4% driven by optimized multi-tenant cloud cost efficiencies."
    )

    p3 = (
        "SECTION 3: CLOUD INFRASTRUCTURE & ARCHITECTURAL TOPOLOGY\n"
        "The Nexus Global Platform operates on an active-active Kubernetes deployment across AWS and GCP.\n"
        "Primary Production Regions: us-east-1 (N. Virginia) and eu-central-1 (Frankfurt).\n"
        "Production Availability: Maintained a 99.98% platform SLA with zero catastrophic outages in 2024.\n"
        "Database Architecture: High-throughput distributed PostgreSQL clusters with pgvector for semantic search.\n"
        "Security: Hardware security modules (HSM) enforce AES-256 encryption at rest and TLS 1.3 in transit."
    )

    p4 = (
        "SECTION 4: HUMAN RESOURCES & ORGANIZATIONAL TALENT\n"
        "Total full-time headcount grew to 580 employees by December 31, 2024.\n"
        "Departmental Breakdown:\n"
        "- Engineering: 320 employees\n"
        "- Product & Design: 85 employees\n"
        "- Sales & Marketing: 110 employees\n"
        "- Customer Support: 65 employees\n"
        "Voluntary attrition rate dropped to an industry-leading 4.2% following the implementation of flexible work."
    )

    p5 = (
        "SECTION 5: REGULATORY COMPLIANCE & INTELLECTUAL PROPERTY\n"
        "Compliance Certifications:\n"
        "- ISO/IEC 27001:2022 renewal was successfully certified on August 14, 2024, valid through 2027.\n"
        "- SOC 2 Type II audit report issued with zero non-conformities.\n"
        "- European Union GDPR compliance certified by independent external audit in September 2024.\n"
        "Patents: United States Patent US-10928374 for 'Distributed Semantic Vector Routing' was officially granted."
    )

    p6 = (
        "SECTION 6: STRATEGIC INITIATIVES & 2025 OUTLOOK\n"
        "Project Apollo: Next-generation autonomous agent orchestration allocated an R&D capital expenditure of $18.5 million.\n"
        "Project Boreas: Edge compute deployment scheduled for public release in Q2 2025.\n"
        "International expansion plans target Tokyo, Japan in Q3 2025 and Sydney, Australia in Q4 2025.\n"
        "Projected FY2025 revenue target is set at $110 million."
    )

    return make_pdf([p1, p2, p3, p4, p5, p6])


def send_chat_query(conv_id: str, doc_id: str, message: str) -> Dict[str, Any]:
    """Sends a chat request and parses the SSE stream output."""
    t0 = time.time()
    payload = {
        "conversation_id": conv_id,
        "message": message,
        "document_ids": [doc_id],
    }
    resp = requests.post(f"{BASE_URL}/api/chat", json=payload, stream=True, timeout=60)

    tokens = []
    done_payload = {}
    routing_plan = {}
    tools_called = []
    current_event = None

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:].strip()
            try:
                parsed = json.loads(data_str)
                if current_event == "token":
                    tokens.append(parsed.get("text", ""))
                elif current_event == "tool_call":
                    tools_called.append(parsed.get("tool"))
                elif current_event == "plan":
                    routing_plan = parsed
                elif current_event == "done":
                    done_payload = parsed
            except Exception:
                pass

    latency = time.time() - t0
    answer = "".join(tokens).strip()
    citations = done_payload.get("citations", [])
    usage = done_payload.get("usage", {}) or {}

    return {
        "answer": answer,
        "citations": citations,
        "usage": usage,
        "latency": round(latency, 2),
        "tools_called": tools_called,
        "routing_plan": routing_plan,
    }


async def setup_indexed_document(pdf_bytes: bytes) -> Tuple[str, str]:
    """Uploads document and indexes it into pgvector chunks."""
    conv_id = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Direct vs RAG Eval"}).json()["id"]

    # Upload document
    files = {"files": ("nexus_annual_report_2024.pdf", pdf_bytes, "application/pdf")}
    upload_res = requests.post(f"{BASE_URL}/api/conversations/{conv_id}/documents", files=files).json()
    if isinstance(upload_res, dict) and "documents" in upload_res:
        doc_id = upload_res["documents"][0]["id"]
    elif isinstance(upload_res, list):
        doc_id = upload_res[0]["id"]
    else:
        doc_id = upload_res["id"]

    # Wait for document to reach ready/parsed
    for _ in range(30):
        doc_info = requests.get(f"{BASE_URL}/api/documents/{doc_id}").json()
        if doc_info["status"] == "ready":
            break
        await asyncio.sleep(1)

    # Parse and index document for RAG evaluation
    print(f"Parsing document {doc_id} with Docling...")
    await parse_document_task(uuid.UUID(doc_id))
    print(f"Indexing chunks for document {doc_id} into pgvector...")
    await index_document_task(uuid.UUID(doc_id))

    return conv_id, doc_id


async def main():
    print("=" * 80)
    print("STAGE 7 EVALUATION: DIRECT MODE vs RAG MODE (10 QUESTIONS)")
    print("=" * 80)

    pdf_bytes = create_evaluation_document()
    conv_id, doc_id = await setup_indexed_document(pdf_bytes)
    print(f"Test Document ID: {doc_id} in Conversation {conv_id}")

    # Verify document is indexed and eligible for both Direct & RAG
    doc_info = requests.get(f"{BASE_URL}/api/documents/{doc_id}").json()
    print(f"Document: {doc_info['filename']} | Pages: {doc_info['page_count']} | Mode: {doc_info['mode']} | IndexStatus: {doc_info['index_status']} | Chunks: {doc_info['chunks_count']}")

    questions = [
        # 1. Factual Lookup
        {
            "id": "Q1",
            "category": "Factual Lookup",
            "question": "Who serves as the Chief Financial Officer (CFO) of Nexus Corporation?",
            "check": lambda ans: "Elena Rostova" in ans,
            "target_page": 1,
        },
        {
            "id": "Q2",
            "category": "Factual Lookup",
            "question": "What is the US patent number granted to Nexus Corporation?",
            "check": lambda ans: "10928374" in ans or "US-10928374" in ans,
            "target_page": 5,
        },
        {
            "id": "Q3",
            "category": "Factual Lookup",
            "question": "What platform availability SLA was maintained in 2024?",
            "check": lambda ans: "99.98" in ans,
            "target_page": 3,
        },
        # 2. Table Extraction
        {
            "id": "Q4",
            "category": "Table Extraction",
            "question": "What was the R&D spend and Net Profit in Q3 2024 according to the performance table?",
            "check": lambda ans: "5.1" in ans and "9.1" in ans,
            "target_page": 2,
        },
        {
            "id": "Q5",
            "category": "Table Extraction",
            "question": "What were the Operating Expenses in Q4 2024?",
            "check": lambda ans: "13.5" in ans,
            "target_page": 2,
        },
        # 3. Multi-hop / Cross Section
        {
            "id": "Q6",
            "category": "Multi-hop",
            "question": "Compare the capital expenditure budget for Project Apollo with the R&D spend in Q1 2024.",
            "check": lambda ans: ("18.5" in ans) and ("4.2" in ans),
            "target_page": [2, 6],
        },
        {
            "id": "Q7",
            "category": "Multi-hop",
            "question": "How many total employees work in Engineering and Product & Design combined?",
            "check": lambda ans: ("405" in ans) or ("320" in ans and "85" in ans),
            "target_page": 4,
        },
        {
            "id": "Q8",
            "category": "Multi-hop",
            "question": "Which international cities are targeted for expansion, and in which quarters of 2025?",
            "check": lambda ans: "Tokyo" in ans and "Sydney" in ans and "Q3" in ans and "Q4" in ans,
            "target_page": 6,
        },
        # 4. Absent Information / Negative Testing
        {
            "id": "Q9",
            "category": "Absent / Negative",
            "question": "What is the recommended dark chocolate cake recipe in the report?",
            "check": lambda ans: any(w in ans.lower() for w in ["not contain", "does not contain", "no mention", "not found"]),
            "target_page": None,
        },
        {
            "id": "Q10",
            "category": "Absent / Negative",
            "question": "What was the company's litigation settlement with Acme Corp in 2024?",
            "check": lambda ans: any(w in ans.lower() for w in ["not contain", "does not contain", "no mention", "not found"]),
            "target_page": None,
        },
    ]

    results = []

    print("\nRunning Evaluation Matrix...")
    for q in questions:
        print(f"\nEvaluating {q['id']} ({q['category']}): {q['question']}")

        # --------------------------------------------------------------------
        # 1. DIRECT MODE EVALUATION
        # --------------------------------------------------------------------
        # Set mode_override to 'direct'
        requests.patch(f"{BASE_URL}/api/documents/{doc_id}/mode-override", json={"mode_override": "direct"})
        # Clean conversation history between tests to prevent context leak
        async with async_session_factory() as db:
            from sqlalchemy import delete
            await db.execute(delete(Message).where(Message.conversation_id == uuid.UUID(conv_id)))
            await db.commit()

        direct_res = send_chat_query(conv_id, doc_id, q["question"])
        direct_correct = q["check"](direct_res["answer"])
        direct_pages = [c.get("page") or c.get("page_start") for c in direct_res["citations"]]
        direct_pages = [p for p in direct_pages if p is not None]
        if q["target_page"] is None:
            direct_cite_correct = len(direct_pages) == 0
        elif isinstance(q["target_page"], list):
            direct_cite_correct = any(p in direct_pages for p in q["target_page"])
        else:
            direct_cite_correct = q["target_page"] in direct_pages

        # --------------------------------------------------------------------
        # 2. RAG MODE EVALUATION
        # --------------------------------------------------------------------
        # Set mode_override to 'rag'
        requests.patch(f"{BASE_URL}/api/documents/{doc_id}/mode-override", json={"mode_override": "rag"})
        # Clean conversation history between tests
        async with async_session_factory() as db:
            from sqlalchemy import delete
            await db.execute(delete(Message).where(Message.conversation_id == uuid.UUID(conv_id)))
            await db.commit()

        rag_res = send_chat_query(conv_id, doc_id, q["question"])
        rag_correct = q["check"](rag_res["answer"])
        rag_pages = [c.get("page") or c.get("page_start") for c in rag_res["citations"]]
        rag_pages = [p for p in rag_pages if p is not None]
        if q["target_page"] is None:
            rag_cite_correct = len(rag_pages) == 0
        elif isinstance(q["target_page"], list):
            rag_cite_correct = any(p in rag_pages for p in q["target_page"])
        else:
            rag_cite_correct = q["target_page"] in rag_pages

        row = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "direct_correct": direct_correct,
            "direct_cites": direct_cite_correct,
            "direct_tokens": direct_res["usage"].get("total_tokens", 0),
            "direct_latency": direct_res["latency"],
            "rag_correct": rag_correct,
            "rag_cites": rag_cite_correct,
            "rag_tokens": rag_res["usage"].get("total_tokens", 0),
            "rag_latency": rag_res["latency"],
            "rag_tools": len(rag_res["tools_called"]),
        }
        results.append(row)
        print(f"  Direct: Correct={direct_correct}, Cites={direct_cite_correct}, Latency={direct_res['latency']}s, Tokens={row['direct_tokens']}")
        print(f"  RAG:    Correct={rag_correct}, Cites={rag_cite_correct}, Latency={rag_res['latency']}s, Tokens={row['rag_tokens']}, Tools={row['rag_tools']}")

    print("\n" + "=" * 120)
    print("COMPARISON RESULTS SUMMARY TABLE")
    print("=" * 120)
    print(f"{'ID':<4} | {'Category':<16} | {'Direct OK?':<10} | {'RAG OK?':<8} | {'Direct Cites':<12} | {'RAG Cites':<10} | {'Direct Tok':<10} | {'RAG Tok':<8} | {'Direct Lat':<10} | {'RAG Lat':<8}")
    print("-" * 120)
    for r in results:
        print(f"{r['id']:<4} | {r['category']:<16} | {'YES' if r['direct_correct'] else 'NO':<10} | {'YES' if r['rag_correct'] else 'NO':<8} | {'YES' if r['direct_cites'] else 'NO':<12} | {'YES' if r['rag_cites'] else 'NO':<10} | {r['direct_tokens']:<10} | {r['rag_tokens']:<8} | {str(r['direct_latency']) + 's':<10} | {str(r['rag_latency']) + 's':<8}")

    # Output JSON for reporting
    with open("app/eval/evaluation_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nSaved evaluation results to app/eval/evaluation_results.json")


if __name__ == "__main__":
    asyncio.run(main())
