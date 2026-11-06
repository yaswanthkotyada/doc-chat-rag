"""
Citation parser and validator for document-grounded responses.
"""
from dataclasses import dataclass
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Regex pattern matching [[cite: filename.ext | p.X]] or [[cite: filename.ext]]
CITE_REGEX = re.compile(
    r"\[\[cite:\s*([^\|\]]+?)(?:\s*\|\s*p\.?\s*(\d+))?\s*\]\]",
    re.IGNORECASE
)

# Pattern to detect incomplete cite markers at the end of a streaming chunk
INCOMPLETE_CITE_REGEX = re.compile(r"\[\[(?:cite:[^\]]*)?$")


@dataclass
class Citation:
    document_id: str
    filename: str
    page: Optional[int]
    marker_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "page": self.page,
            "marker_text": self.marker_text,
        }


def parse_and_validate_citations(
    text: str,
    documents: List[Any]
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Parse citation markers from generated text and validate against actual documents:
    - Unknown filename -> drop marker from text and log warning.
    - Valid file, page > page_count -> keep file reference, drop page number.
    - Duplicate filenames in conversation -> match first matching document by order of attachment.
    - Normalizes marker text in cleaned string.

    Returns:
        (cleaned_text, list_of_validated_citations)
    """
    if not text:
        return "", []

    # Map normalized lowercase filename to document list
    docs_by_name: Dict[str, List[Any]] = {}
    for doc in documents:
        fname = getattr(doc, "filename", None) or (doc.get("filename") if isinstance(doc, dict) else None)
        if fname:
            key = fname.strip().lower()
            docs_by_name.setdefault(key, []).append(doc)

    validated_citations: List[Dict[str, Any]] = []
    seen_citation_keys = set()

    def replace_match(match: re.Match) -> str:
        raw_filename = match.group(1).strip().strip("'\"")
        raw_page = match.group(2)
        norm_key = raw_filename.lower()

        # 1. Look up document by filename
        candidates = docs_by_name.get(norm_key)
        if not candidates:
            logger.warning("Dropping invalid citation marker referencing unknown document: %r", raw_filename)
            return ""

        # Disambiguation: choose first matching document in conversation
        matched_doc = candidates[0]
        doc_id = str(getattr(matched_doc, "id", None) or matched_doc.get("id"))
        doc_filename = getattr(matched_doc, "filename", None) or matched_doc.get("filename")
        doc_page_count = getattr(matched_doc, "page_count", None) or (matched_doc.get("page_count") if isinstance(matched_doc, dict) else None)

        # 2. Validate page number
        page_val: Optional[int] = None
        if raw_page is not None:
            try:
                parsed_page = int(raw_page)
                if doc_page_count is not None and parsed_page > doc_page_count:
                    # Page exceeds page count: keep file, drop page
                    logger.warning(
                        "Citation page %d exceeds page_count %d for %s; dropping page number",
                        parsed_page, doc_page_count, doc_filename
                    )
                    page_val = None
                else:
                    page_val = parsed_page
            except ValueError:
                page_val = None

        # 3. Construct normalized marker
        if page_val is not None:
            norm_marker = f"[[cite: {doc_filename} | p.{page_val}]]"
        else:
            norm_marker = f"[[cite: {doc_filename}]]"

        # 4. Record unique citation
        cite_key = (doc_id, page_val)
        if cite_key not in seen_citation_keys:
            seen_citation_keys.add(cite_key)
            validated_citations.append({
                "document_id": doc_id,
                "filename": doc_filename,
                "page": page_val,
                "marker_text": norm_marker,
            })

        return norm_marker

    # Perform replacement
    cleaned_text = CITE_REGEX.sub(replace_match, text)

    # Clean up any duplicate spacing introduced by dropped markers
    cleaned_text = re.sub(r"  +", " ", cleaned_text)
    # Clean up space before punctuation
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
        """
        Append chunk, hold back incomplete marker fragments, and return safe printable text.
        """
        combined = self.buffer + chunk
        self.buffer = ""

        # Check if there is an unclosed `[[` or `[[cite:` at the end
        match = INCOMPLETE_CITE_REGEX.search(combined)
        if match:
            split_idx = match.start()
            self.buffer = combined[split_idx:]
            return combined[:split_idx]

        return combined

    def flush(self) -> str:
        """Flush any remaining buffered text."""
        remaining = self.buffer
        self.buffer = ""
        return remaining

