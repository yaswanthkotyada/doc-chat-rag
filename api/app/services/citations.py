"""
Stage 7 - Enhanced Citation Parser & Resolver: services/citations.py

Parses and validates citations from both Direct mode and RAG mode:
- Direct mode: [[cite: filename.ext | p.X]] or [[cite: filename.ext]]
- RAG mode: [cite: R1] or [cite: R1, R2] or [[cite: R1]]
- Resolves result IDs against the ToolRegistryItem mapping to real document filenames and page ranges.
- Converts result IDs into canonical [[cite: filename.pdf | p.X]] or [[cite: filename.pdf | p.X-Y]] markers.
- Drops invalid or invented IDs/filenames and logs warnings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Matches [cite: filename.ext | p.X] or [[cite: filename.ext | p.X]] or [cite: R1] or [cite: R1, R2]
CITE_MARKER_REGEX = re.compile(
    r"\[{1,2}cite:\s*([^\|\[\]]+?)(?:\s*\|\s*p\.?\s*(\d+(?:\s*-\s*\d+)?))?\s*\]{1,2}",
    re.IGNORECASE,
)

# Detect incomplete markers at the end of streaming tokens
INCOMPLETE_CITE_REGEX = re.compile(r"\[{1,2}(?:cite:[^\]]*)?$")


@dataclass
class Citation:
    document_id: str
    filename: str
    page: Optional[int]
    marker_text: str
    page_end: Optional[int] = None
    chunk_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "document_id": self.document_id,
            "filename": self.filename,
            "page": self.page,
            "marker_text": self.marker_text,
        }
        if self.page_end is not None:
            d["page_end"] = self.page_end
        if self.chunk_id is not None:
            d["chunk_id"] = self.chunk_id
        return d


def parse_and_validate_citations(
    text: str,
    documents: List[Any],
    result_registry: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Parse citation markers from generated text and validate against actual documents:
    - Resolves RAG result IDs (e.g. 'R1', 'R2') via result_registry into canonical document and page ranges.
    - Resolves direct filename citations (e.g. 'filename.pdf | p.3') via documents list.
    - Drops invalid or invented result IDs / filenames and logs warnings.
    - Normalizes marker text in cleaned string.

    Returns:
        (cleaned_text, list_of_validated_citations)
    """
    if not text:
        return "", []

    docs_by_name: Dict[str, List[Any]] = {}
    for doc in documents:
        fname = getattr(doc, "filename", None) or (doc.get("filename") if isinstance(doc, dict) else None)
        if fname:
            docs_by_name.setdefault(fname.strip().lower(), []).append(doc)

    validated_citations: List[Dict[str, Any]] = []
    seen_citation_keys = set()

    def replace_match(match: re.Match) -> str:
        raw_first = match.group(1).strip()
        raw_page = match.group(2)

        # Check if first part contains RAG result IDs: e.g. "R1" or "R1, R2"
        tokens = [t.strip() for t in raw_first.split(",") if t.strip()]
        is_rag_ids = False
        if result_registry and any(re.match(r"^R\d+$", t, re.IGNORECASE) for t in tokens):
            is_rag_ids = True

        if is_rag_ids and result_registry:
            resolved_markers = []
            for token in tokens:
                id_match = re.match(r"^(R\d+)$", token, re.IGNORECASE)
                if not id_match:
                    continue
                res_id = id_match.group(1).upper()
                reg_item = result_registry.get(res_id)

                if not reg_item:
                    logger.warning("Dropping invalid or invented RAG citation ID: %r", res_id)
                    continue

                doc_id = str(getattr(reg_item, "document_id", ""))
                doc_filename = getattr(reg_item, "document_filename", "")
                p_start = getattr(reg_item, "page_start", None)
                p_end = getattr(reg_item, "page_end", None)
                chunk_id = str(getattr(reg_item, "chunk_id", ""))

                if p_start is not None and p_end is not None:
                    if p_start == p_end:
                        norm_marker = f"[[cite: {doc_filename} | p.{p_start}]]"
                    else:
                        norm_marker = f"[[cite: {doc_filename} | p.{p_start}-{p_end}]]"
                else:
                    norm_marker = f"[[cite: {doc_filename}]]"

                resolved_markers.append(norm_marker)

                cite_key = (doc_id, p_start, p_end, chunk_id)
                if cite_key not in seen_citation_keys:
                    seen_citation_keys.add(cite_key)
                    validated_citations.append({
                        "document_id": doc_id,
                        "filename": doc_filename,
                        "page": p_start,
                        "page_end": p_end,
                        "chunk_id": chunk_id,
                        "marker_text": norm_marker,
                    })

            return " ".join(resolved_markers)

        # Direct mode: filename and optional page number
        raw_filename = raw_first.strip("'\"")
        norm_key = raw_filename.lower()
        candidates = docs_by_name.get(norm_key)

        if not candidates:
            logger.warning("Dropping invalid citation marker referencing unknown document: %r", raw_filename)
            return ""

        matched_doc = candidates[0]
        doc_id = str(getattr(matched_doc, "id", None) or matched_doc.get("id"))
        doc_filename = getattr(matched_doc, "filename", None) or matched_doc.get("filename")
        doc_page_count = getattr(matched_doc, "page_count", None) or (
            matched_doc.get("page_count") if isinstance(matched_doc, dict) else None
        )

        page_val: Optional[int] = None
        if raw_page:
            try:
                # Handle single page e.g. "1" or range "1-3"
                p_str = raw_page.split("-")[0].strip()
                parsed_p = int(p_str)
                if doc_page_count and parsed_p > doc_page_count:
                    logger.warning("Citation page %d exceeds page_count %d for %s; dropping page", parsed_p, doc_page_count, doc_filename)
                    page_val = None
                elif parsed_p >= 1:
                    page_val = parsed_p
            except ValueError:
                page_val = None

        if page_val is not None:
            norm_marker = f"[[cite: {doc_filename} | p.{page_val}]]"
        else:
            norm_marker = f"[[cite: {doc_filename}]]"

        cite_key = (doc_id, page_val, None, None)
        if cite_key not in seen_citation_keys:
            seen_citation_keys.add(cite_key)
            validated_citations.append({
                "document_id": doc_id,
                "filename": doc_filename,
                "page": page_val,
                "marker_text": norm_marker,
            })

        return norm_marker

    cleaned_text = CITE_MARKER_REGEX.sub(replace_match, text)

    # Clean up duplicate spacing or floating punctuation
    cleaned_text = re.sub(r"  +", " ", cleaned_text)
    cleaned_text = re.sub(r" ([.,;:!?])", r"\1", cleaned_text)

    return cleaned_text, validated_citations


class StreamCitationBuffer:
    """
    Helper for handling streaming chunks that may split a [[cite: ...]] marker
    across multiple tokens without visual flicker.
    """

    def __init__(self):
        self.buffer = ""

    def process_chunk(self, chunk: str) -> str:
        combined = self.buffer + chunk
        self.buffer = ""

        match = INCOMPLETE_CITE_REGEX.search(combined)
        if match:
            split_idx = match.start()
            self.buffer = combined[split_idx:]
            return combined[:split_idx]

        return combined

    def flush(self) -> str:
        remaining = self.buffer
        self.buffer = ""
        return remaining
