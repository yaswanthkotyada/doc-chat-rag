"""
Unit tests for Stage 7 Document Routing Service: services/router.py
"""

import uuid
import pytest
from app.config import settings
from app.models.document import Document
from app.services.router import check_override_eligibility, route_documents


def _make_doc(
    filename: str = "test.pdf",
    mode: str = "direct",
    status: str = "ready",
    page_count: int = 10,
    size_bytes: int = 1024 * 1024,
    index_status: str = None,
    parse_status: str = None,
    mode_override: str = None,
) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        filename=filename,
        mime_type="application/pdf" if filename.endswith(".pdf") else "text/plain",
        size_bytes=size_bytes,
        sha256="abc123sha256",
        status=status,
        page_count=page_count,
        mode=mode,
        index_status=index_status,
        parse_status=parse_status,
    )
    doc.mode_override = mode_override
    return doc


def test_route_direct_mode():
    doc1 = _make_doc("small.pdf", mode="direct", status="ready", page_count=5)
    plan = route_documents([doc1])

    assert plan.mode == "direct"
    assert len(plan.direct_documents) == 1
    assert len(plan.rag_documents) == 0
    assert len(plan.excluded_documents) == 0
    assert plan.direct_documents[0].filename == "small.pdf"


def test_route_rag_mode():
    doc1 = _make_doc("large.pdf", mode="rag", status="ready", page_count=80, index_status="indexed")
    plan = route_documents([doc1])

    assert plan.mode == "rag"
    assert len(plan.direct_documents) == 0
    assert len(plan.rag_documents) == 1
    assert len(plan.excluded_documents) == 0
    assert plan.rag_documents[0].filename == "large.pdf"


def test_route_mixed_mode():
    doc_direct = _make_doc("small.pdf", mode="direct", status="ready", page_count=5)
    doc_rag = _make_doc("large.pdf", mode="rag", status="ready", page_count=80, index_status="indexed")

    plan = route_documents([doc_direct, doc_rag])

    assert plan.mode == "mixed"
    assert len(plan.direct_documents) == 1
    assert len(plan.rag_documents) == 1
    assert len(plan.excluded_documents) == 0


def test_route_excluded_unindexed_rag_doc():
    doc_indexing = _make_doc("indexing.pdf", mode="rag", status="ready", index_status="indexing")
    doc_parsing = _make_doc("parsing.pdf", mode="rag", status="ready", parse_status="parsing")
    doc_failed = _make_doc("failed.pdf", mode="rag", status="ready", index_status="failed")

    plan = route_documents([doc_indexing, doc_parsing, doc_failed])

    assert plan.mode == "none"
    assert len(plan.direct_documents) == 0
    assert len(plan.rag_documents) == 0
    assert len(plan.excluded_documents) == 3
    assert any("still parsing or indexing" in e.reason for e in plan.excluded_documents)
    assert any("Indexing failed" in e.reason for e in plan.excluded_documents)


def test_manual_override_rag_eligible():
    # Small document with mode 'direct', but indexed and manually overridden to 'rag'
    doc = _make_doc("small.pdf", mode="direct", status="ready", page_count=5, index_status="indexed", mode_override="rag")

    plan = route_documents([doc])
    assert plan.mode == "rag"
    assert len(plan.rag_documents) == 1
    assert len(plan.direct_documents) == 0


def test_manual_override_rag_ineligible():
    # Small document with mode 'direct', but NOT indexed; overridden to 'rag'
    doc = _make_doc("small.pdf", mode="direct", status="ready", page_count=5, index_status=None, mode_override="rag")

    plan = route_documents([doc])
    assert plan.mode == "none"
    assert len(plan.rag_documents) == 0
    assert len(plan.excluded_documents) == 1
    assert "cannot be overridden to RAG because it is not indexed" in plan.excluded_documents[0].reason


def test_manual_override_direct_eligible():
    # Mid-size document with mode 'rag', but within direct limits (e.g. 25 pages), overridden to 'direct'
    doc = _make_doc("contract.pdf", mode="rag", status="ready", page_count=25, size_bytes=5 * 1024 * 1024, mode_override="direct")

    plan = route_documents([doc])
    assert plan.mode == "direct"
    assert len(plan.direct_documents) == 1
    assert len(plan.rag_documents) == 0


def test_manual_override_direct_ineligible_page_limit():
    # 60 pages exceeds DIRECT_MAX_PAGES (40)
    doc = _make_doc("huge.pdf", mode="rag", status="ready", page_count=60, mode_override="direct")

    plan = route_documents([doc])
    assert plan.mode == "none"
    assert len(plan.direct_documents) == 0
    assert len(plan.excluded_documents) == 1
    assert "exceeds Direct mode limit" in plan.excluded_documents[0].reason


def test_routing_plan_to_dict():
    doc_direct = _make_doc("memo.txt", mode="direct", status="ready")
    doc_rag = _make_doc("spec.pdf", mode="rag", status="ready", index_status="indexed")

    plan = route_documents([doc_direct, doc_rag])
    d = plan.to_dict()

    assert d["mode"] == "mixed"
    assert len(d["direct_documents"]) == 1
    assert len(d["rag_documents"]) == 1
    assert d["direct_documents"][0]["filename"] == "memo.txt"
    assert d["rag_documents"][0]["filename"] == "spec.pdf"
