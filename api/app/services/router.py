"""
Stage 7 - Routing Service: services/router.py

Pure routing service that classifies documents for a chat request into:
- Direct mode: attached directly as file parts (Stage 4)
- RAG mode: covered by search_documents tool (Stage 6)
- Excluded: still processing/indexing, failed, or ineligible override, with safe user-facing reasons.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.models.document import Document

logger = logging.getLogger(__name__)


@dataclass
class ExcludedDocumentInfo:
    id: str
    filename: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "reason": self.reason,
        }


@dataclass
class RoutingPlan:
    direct_documents: List[Document] = field(default_factory=list)
    rag_documents: List[Document] = field(default_factory=list)
    excluded_documents: List[ExcludedDocumentInfo] = field(default_factory=list)
    mode: str = "none"  # 'direct' | 'rag' | 'mixed' | 'none'
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "summary": self.summary,
            "direct_documents": [
                {
                    "id": str(d.id),
                    "filename": d.filename,
                    "mime_type": d.mime_type,
                    "page_count": d.page_count,
                    "size_bytes": d.size_bytes,
                    "mode_override": getattr(d, "mode_override", None),
                }
                for d in self.direct_documents
            ],
            "rag_documents": [
                {
                    "id": str(d.id),
                    "filename": d.filename,
                    "chunks_count": getattr(d, "chunks_count", 0),
                    "page_count": d.page_count,
                    "mode_override": getattr(d, "mode_override", None),
                }
                for d in self.rag_documents
            ],
            "excluded_documents": [e.to_dict() for e in self.excluded_documents],
        }


def check_override_eligibility(doc: Document, target_mode: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a document is eligible for a manual mode override.
    - target_mode == 'rag': must be indexed in chunks table.
    - target_mode == 'direct': must not exceed direct page/size limits.
    """
    if target_mode == "rag":
        if getattr(doc, "index_status", None) == "indexed":
            return True, None
        return False, f"Document '{doc.filename}' cannot be overridden to RAG because it is not indexed (status: {getattr(doc, 'index_status', 'not indexed')})."

    elif target_mode == "direct":
        max_bytes = settings.DIRECT_MAX_MB * 1024 * 1024
        if doc.size_bytes > max_bytes:
            mb = round(doc.size_bytes / (1024 * 1024), 1)
            return False, f"Document '{doc.filename}' ({mb}MB) exceeds Direct mode size limit of {settings.DIRECT_MAX_MB}MB."

        if doc.page_count is not None and doc.page_count > settings.DIRECT_MAX_PAGES:
            return False, f"Document '{doc.filename}' ({doc.page_count} pages) exceeds Direct mode limit of {settings.DIRECT_MAX_PAGES} pages."

        if doc.status != "ready":
            return False, f"Document '{doc.filename}' is not ready (status: {doc.status})."

        return True, None

    return False, f"Unknown mode override '{target_mode}'."


def route_documents(documents: List[Document]) -> RoutingPlan:
    """
    Pure router that assigns each attached document to Direct, RAG, or Excluded.
    Enforces mode_override when valid; falls back to default mode; records clear reasons.
    """
    direct_docs: List[Document] = []
    rag_docs: List[Document] = []
    excluded_docs: List[ExcludedDocumentInfo] = []

    for doc in documents:
        doc_id_str = str(doc.id)
        override = getattr(doc, "mode_override", None)

        # 1. Handle manual mode override if specified
        if override:
            is_valid, reason = check_override_eligibility(doc, override)
            if not is_valid:
                excluded_docs.append(ExcludedDocumentInfo(id=doc_id_str, filename=doc.filename, reason=reason or "Ineligible override"))
                continue

            if override == "rag":
                rag_docs.append(doc)
            elif override == "direct":
                direct_docs.append(doc)
            continue

        # 2. Automatic routing based on document.mode
        doc_mode = getattr(doc, "mode", None) or "direct"

        if doc_mode == "rag":
            idx_status = getattr(doc, "index_status", None)
            if idx_status == "indexed":
                rag_docs.append(doc)
            elif idx_status == "indexing" or getattr(doc, "parse_status", None) in ("pending", "parsing"):
                excluded_docs.append(
                    ExcludedDocumentInfo(
                        id=doc_id_str,
                        filename=doc.filename,
                        reason=f"Document '{doc.filename}' is still parsing or indexing; please wait a moment."
                    )
                )
            elif idx_status == "failed":
                err = getattr(doc, "index_error", None) or "Indexing failed"
                excluded_docs.append(ExcludedDocumentInfo(id=doc_id_str, filename=doc.filename, reason=f"Indexing failed: {err}"))
            elif getattr(doc, "parse_status", None) == "failed":
                err = getattr(doc, "parse_error", None) or "Parsing failed"
                excluded_docs.append(ExcludedDocumentInfo(id=doc_id_str, filename=doc.filename, reason=f"Parsing failed: {err}"))
            else:
                excluded_docs.append(
                    ExcludedDocumentInfo(
                        id=doc_id_str,
                        filename=doc.filename,
                        reason=f"Document '{doc.filename}' is not indexed yet."
                    )
                )

        else:
            # Direct mode
            if doc.status == "ready":
                direct_docs.append(doc)
            elif doc.status in ("uploading", "processing"):
                excluded_docs.append(
                    ExcludedDocumentInfo(
                        id=doc_id_str,
                        filename=doc.filename,
                        reason=f"Document '{doc.filename}' is still uploading/processing."
                    )
                )
            elif doc.status == "failed":
                err = getattr(doc, "error", None) or "Processing failed"
                excluded_docs.append(ExcludedDocumentInfo(id=doc_id_str, filename=doc.filename, reason=f"Processing failed: {err}"))
            else:
                excluded_docs.append(
                    ExcludedDocumentInfo(
                        id=doc_id_str,
                        filename=doc.filename,
                        reason=f"Document '{doc.filename}' is not ready."
                    )
                )

    # 3. Determine overall mode
    if direct_docs and rag_docs:
        overall_mode = "mixed"
        summary = f"Mixed mode: {len(direct_docs)} direct file(s) and {len(rag_docs)} RAG document(s) searchable."
    elif rag_docs:
        overall_mode = "rag"
        summary = f"RAG mode: {len(rag_docs)} indexed document(s) searchable via tool calling."
    elif direct_docs:
        overall_mode = "direct"
        summary = f"Direct mode: {len(direct_docs)} document(s) attached directly."
    else:
        overall_mode = "none"
        if excluded_docs:
            summary = f"No documents available: {len(excluded_docs)} document(s) excluded."
        else:
            summary = "No documents attached."

    return RoutingPlan(
        direct_documents=direct_docs,
        rag_documents=rag_docs,
        excluded_documents=excluded_docs,
        mode=overall_mode,
        summary=summary,
    )

