"""
Stage 6 - Milestone 1: Structure-aware, deterministic document chunker.

Input:  raw_json (the Docling JSON dict stored in parsed/docling.json)
        OR a list of ParsedPage objects from document_pages.
Output: list of Chunk dataclass instances, one list per document.

Design decisions:
 - Structure-aware: splits at headings first, then paragraphs, never mid-sentence
   unless a single sentence exceeds CHUNK_MAX_TOKENS.
 - Tables are kept whole when they fit; split by rows (repeating header) otherwise.
 - Chunks may span pages; page_start / page_end are always accurate.
 - Overlap (CHUNK_OVERLAP_TOKENS) is applied only between consecutive text chunks
   in the same section to give context continuity.
 - Tiny chunks (< CHUNK_MIN_TOKENS) are merged into their neighbour.
 - Deterministic: same input → same output (no randomness, no UUIDs here).
 - Token counting is done locally with tiktoken (cl100k_base) – no API calls.
 - Works from BOTH Docling JSON (preferred – richer structure) and fallback
   per-page markdown (plain list of ParsedPage).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text, disallowed_special=()))

except ImportError:  # fallback if tiktoken not installed in older envs
    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        # rough heuristic: 4 chars ≈ 1 token
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

CHUNK_TARGET_TOKENS: int = 600
CHUNK_MAX_TOKENS: int = 900
CHUNK_OVERLAP_TOKENS: int = 80
CHUNK_MIN_TOKENS: int = 60


@dataclass
class Chunk:
    """A single chunk ready for embedding and storage."""

    chunk_index: int
    text: str            # what the LLM reads
    embed_text: str      # what gets embedded (may include context prefix)
    page_start: int      # 1-based, inclusive
    page_end: int        # 1-based, inclusive
    heading_path: List[str] = field(default_factory=list)
    chunk_type: str = "text"  # 'text' | 'table' | 'list' | 'mixed'
    token_count: int = 0
    char_start: Optional[int] = None
    char_end: Optional[int] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Regex patterns
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_MD_TABLE_RE = re.compile(
    r"(?:^[^\n]*\|[^\n]*\n){1,}(?:^[ \t]*[-|: \t]+\n)(?:^[^\n]*\|[^\n]*\n)*",
    re.MULTILINE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences; keep each non-empty."""
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _last_n_tokens(text: str, n: int) -> str:
    """Return approximately the last *n* tokens of *text* as a string."""
    if not text:
        return ""
    tokens = _ENC.encode(text, disallowed_special=()) if hasattr(_ENC, "encode") else []  # type: ignore[name-defined]
    if not tokens:
        # fallback character-based
        chars = n * 4
        return text[-chars:]
    return _ENC.decode(tokens[-n:])  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Table parsing helpers
# ---------------------------------------------------------------------------

def _parse_md_table(table_md: str) -> Tuple[List[str], List[List[str]]]:
    """Parse a markdown table into (header_cells, data_rows).
    Returns header as list of strings, rows as list of list of strings.
    """
    lines = [l.rstrip() for l in table_md.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return [], []

    def split_row(line: str) -> List[str]:
        # Strip leading/trailing pipe, then split on |
        line = line.strip().strip("|")
        return [c.strip() for c in line.split("|")]

    header = split_row(lines[0])
    # lines[1] is the separator ---
    data_rows = [split_row(l) for l in lines[2:] if l and not re.match(r"^[\s|:-]+$", l)]
    return header, data_rows


def _build_md_table(header: List[str], rows: List[List[str]]) -> str:
    """Rebuild a markdown table from header + rows."""
    sep = "| " + " | ".join(["---"] * len(header)) + " |"
    header_line = "| " + " | ".join(header) + " |"
    row_lines = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([header_line, sep] + row_lines)


def _split_table_into_chunks(
    table_text: str,
    heading_path: List[str],
    page_start: int,
    page_end: int,
    doc_name: str,
    start_index: int,
    max_tokens: int = CHUNK_MAX_TOKENS,
) -> List[Chunk]:
    """Split an oversized markdown table into row-batched chunks, repeating header."""
    header, data_rows = _parse_md_table(table_text)
    if not header or not data_rows:
        # Fallback: treat as single text chunk
        return _make_single_chunk(
            table_text, heading_path, page_start, page_end, doc_name, start_index, "table"
        )

    header_text = _build_md_table(header, [])  # just header+sep line
    # estimate how many rows fit per chunk
    header_tokens = _count_tokens(header_text)
    per_row_approx = sum(_count_tokens(r) for r in [" | ".join(row) for row in data_rows]) / max(len(data_rows), 1)
    rows_per_chunk = max(1, int((max_tokens - header_tokens) / max(per_row_approx, 1)))

    chunks: List[Chunk] = []
    idx = start_index
    for batch_start in range(0, len(data_rows), rows_per_chunk):
        batch = data_rows[batch_start : batch_start + rows_per_chunk]
        part_md = _build_md_table(header, batch)
        prefix = " > ".join(heading_path) if heading_path else ""
        embed = f"Document: {doc_name}" + (f" > {prefix}" if prefix else "") + "\n" + part_md
        chunks.append(
            Chunk(
                chunk_index=idx,
                text=part_md,
                embed_text=embed,
                page_start=page_start,
                page_end=page_end,
                heading_path=list(heading_path),
                chunk_type="table",
                token_count=_count_tokens(part_md),
            )
        )
        idx += 1
    return chunks


def _make_single_chunk(
    text: str,
    heading_path: List[str],
    page_start: int,
    page_end: int,
    doc_name: str,
    idx: int,
    chunk_type: str = "text",
) -> List[Chunk]:
    prefix = " > ".join(heading_path) if heading_path else ""
    embed = f"Document: {doc_name}" + (f" > {prefix}" if prefix else "") + "\n" + text
    return [
        Chunk(
            chunk_index=idx,
            text=text,
            embed_text=embed,
            page_start=page_start,
            page_end=page_end,
            heading_path=list(heading_path),
            chunk_type=chunk_type,
            token_count=_count_tokens(text),
        )
    ]


# ---------------------------------------------------------------------------
# Core section-to-chunks conversion
# ---------------------------------------------------------------------------

@dataclass
class _Item:
    """Internal representation of a parsed content item."""
    text: str
    item_type: str   # 'heading1'..'heading6', 'table', 'list', 'text'
    level: int       # heading level (1-6) or 0 for non-headings
    page_no: int     # 1-based


def _flush_text_buffer(
    buf: List[_Item],
    heading_path: List[str],
    doc_name: str,
    start_index: int,
    max_tokens: int = CHUNK_MAX_TOKENS,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    min_tokens: int = CHUNK_MIN_TOKENS,
) -> List[Chunk]:
    """
    Turn a buffer of text _Item objects into one or more Chunk objects.
    Applies sentence-level splitting when a paragraph is too large.
    Applies overlap between consecutive chunks within the buffer.
    """
    if not buf:
        return []

    chunks: List[Chunk] = []
    idx = start_index
    current_parts: List[str] = []
    current_tokens = 0
    page_start = buf[0].page_no
    page_end = buf[0].page_no
    prev_chunk_tail: str = ""  # overlap text from previous chunk

    def _emit():
        nonlocal current_parts, current_tokens, page_start, page_end, prev_chunk_tail, idx
        raw = "\n\n".join(current_parts).strip()
        if not raw:
            return
        full_text = (prev_chunk_tail + "\n\n" + raw).strip() if prev_chunk_tail else raw
        toks = _count_tokens(full_text)
        prefix = " > ".join(heading_path) if heading_path else ""
        embed = f"Document: {doc_name}" + (f" > {prefix}" if prefix else "") + "\n" + full_text
        chunks.append(
            Chunk(
                chunk_index=idx,
                text=full_text,
                embed_text=embed,
                page_start=page_start,
                page_end=page_end,
                heading_path=list(heading_path),
                chunk_type="text",
                token_count=toks,
            )
        )
        idx += 1
        # Prepare overlap for next chunk
        prev_chunk_tail = _last_n_tokens(raw, overlap_tokens)
        current_parts = []
        current_tokens = 0

    for item in buf:
        para = item.text.strip()
        if not para:
            continue
        page_end = max(page_end, item.page_no)
        para_tokens = _count_tokens(para)

        if para_tokens > max_tokens:
            # Need to split this paragraph at sentence level
            if current_parts:
                _emit()
                page_start = item.page_no

            sentences = _split_sentences(para)
            sent_buf: List[str] = []
            sent_tokens = 0
            for sent in sentences:
                st = _count_tokens(sent)
                # Flush when we hit target OR when adding this sentence would breach max
                if sent_buf and (sent_tokens + st > target_tokens or sent_tokens + st > max_tokens):
                    current_parts = sent_buf
                    current_tokens = sent_tokens
                    page_start = item.page_no
                    page_end = item.page_no
                    _emit()
                    page_start = item.page_no
                    sent_buf = []
                    sent_tokens = 0
                sent_buf.append(sent)
                sent_tokens += st
                # Safety: if a single sentence is itself > max_tokens, emit it alone
                if sent_tokens > max_tokens:
                    current_parts = sent_buf
                    current_tokens = sent_tokens
                    page_start = item.page_no
                    page_end = item.page_no
                    _emit()
                    page_start = item.page_no
                    sent_buf = []
                    sent_tokens = 0
            if sent_buf:
                current_parts = sent_buf
                current_tokens = sent_tokens
                page_start = item.page_no
                page_end = item.page_no

        elif current_tokens + para_tokens > target_tokens and current_parts:
            # Flushing current buffer before adding this paragraph
            _emit()
            page_start = item.page_no
            page_end = item.page_no
            current_parts.append(para)
            current_tokens += para_tokens
        else:
            if not current_parts:
                page_start = item.page_no
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        _emit()

    return chunks


# ---------------------------------------------------------------------------
# Structural section builder
# ---------------------------------------------------------------------------

@dataclass
class _Section:
    """A section of the document under a heading path."""
    heading_path: List[str]
    items: List[_Item] = field(default_factory=list)


def _items_from_docling_json(raw_json: Dict[str, Any]) -> List[_Item]:
    """
    Extract ordered content items from a Docling JSON document.
    Handles both single-document and batched formats.
    """
    items: List[_Item] = []

    # Batched format: {"batches": [{...}, ...]}
    docs = raw_json.get("batches") if "batches" in raw_json else [raw_json]
    if not docs:
        return items

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        texts = doc.get("texts") or []
        tables = doc.get("tables") or []

        # Build a lookup of ref → page_no for tables (use first prov entry)
        table_page: Dict[str, int] = {}
        for t in tables:
            self_ref = t.get("self_ref", "")
            prov = t.get("prov", [])
            page_no = prov[0].get("page_no", 1) if prov else 1
            table_page[self_ref] = page_no

        # Walk body to get ordered items (preserves document order)
        body = doc.get("body", {})
        body_children = body.get("children", []) if isinstance(body, dict) else []

        # Collect all text items and table items indexed by self_ref
        text_map: Dict[str, _Item] = {}
        for t in texts:
            ref = t.get("self_ref", "")
            prov = t.get("prov", [])
            page_no = prov[0].get("page_no", 1) if prov else 1
            label = t.get("label", "text")
            text_val = t.get("text", "").strip()
            if not text_val:
                continue
            # Determine item type
            level = 0
            if label in ("section_heading",):
                level = 1
                item_type = "heading1"
            elif label == "title":
                level = 1
                item_type = "heading1"
            elif label.startswith("heading"):
                # heading1, heading2, etc.
                try:
                    level = int(label[-1])
                except ValueError:
                    level = 1
                item_type = f"heading{level}"
            elif label == "list_item":
                item_type = "list"
            else:
                item_type = "text"
            text_map[ref] = _Item(text=text_val, item_type=item_type, level=level, page_no=page_no)

        table_map: Dict[str, _Item] = {}
        for t in tables:
            ref = t.get("self_ref", "")
            page_no = table_page.get(ref, 1)
            # Try to get export markdown from captions or data
            export = t.get("data", {})
            grid = export.get("grid", []) if isinstance(export, dict) else []

            # Build markdown from grid
            if grid:
                # First row is header
                header_row = [cell.get("text", "") for cell in grid[0]] if grid else []
                data_rows = [
                    [cell.get("text", "") for cell in row]
                    for row in grid[1:]
                ]
                md = _build_md_table(header_row, data_rows)
            else:
                # Try captions
                captions = t.get("captions", [])
                cap_text = " ".join(c.get("text", "") for c in captions)
                md = cap_text or "[table]"

            table_map[ref] = _Item(text=md, item_type="table", level=0, page_no=page_no)

        # Walk body children in order; fall back to flat lists if body is empty
        seen_refs: set = set()

        def _process_children(children: List[Any]) -> None:
            for child in children:
                if isinstance(child, dict):
                    ref = child.get("$ref", "")
                    if ref in text_map:
                        items.append(text_map[ref])
                        seen_refs.add(ref)
                    elif ref in table_map:
                        items.append(table_map[ref])
                        seen_refs.add(ref)
                    # Recurse into nested children
                    sub = child.get("children", [])
                    if sub:
                        _process_children(sub)

        _process_children(body_children)

        # Any texts not encountered in body walk (body may be missing)
        for ref, item in text_map.items():
            if ref not in seen_refs:
                items.append(item)
                seen_refs.add(ref)

        for ref, item in table_map.items():
            if ref not in seen_refs:
                items.append(item)
                seen_refs.add(ref)

    return items


def _items_from_pages(pages: List[Any]) -> List[_Item]:
    """
    Fallback: build items from ParsedPage / dict list (per-page markdown).
    Uses regex to detect markdown headings.
    """
    items: List[_Item] = []
    for page in pages:
        # Accept either dicts or objects with attributes
        page_no = getattr(page, "page_no", None) or page.get("page_no", 1)
        md = getattr(page, "markdown", None) or page.get("markdown", "") or ""
        if not md.strip():
            continue

        # Split by markdown headings
        parts = re.split(r"(\n#{1,6} [^\n]+)", "\n" + md)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", part)
            if heading_match:
                level = len(heading_match.group(1))
                items.append(_Item(
                    text=heading_match.group(2).strip(),
                    item_type=f"heading{level}",
                    level=level,
                    page_no=page_no,
                ))
            else:
                # Check for tables
                if "|" in part and re.search(r"[-|]{3,}", part):
                    items.append(_Item(text=part, item_type="table", level=0, page_no=page_no))
                else:
                    items.append(_Item(text=part, item_type="text", level=0, page_no=page_no))
    return items


# ---------------------------------------------------------------------------
# Main public entry-point
# ---------------------------------------------------------------------------

def chunk_document(
    doc_name: str,
    raw_json: Optional[Dict[str, Any]] = None,
    pages: Optional[List[Any]] = None,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    min_tokens: int = CHUNK_MIN_TOKENS,
) -> List[Chunk]:
    """
    Chunk a document into a list of Chunk objects.

    Prefer raw_json (Docling structured JSON) if available.
    Falls back to pages (list of ParsedPage or dicts with 'page_no'/'markdown').

    Args:
        doc_name:       Human-readable document name used in embed_text prefix.
        raw_json:       Docling JSON dict (from parsed/docling.json).
        pages:          List of ParsedPage objects or dicts as fallback.
        target_tokens:  Soft target chunk size in tokens.
        max_tokens:     Hard maximum. Chunks (except single sentences) won't exceed this.
        overlap_tokens: Overlap token count between consecutive text chunks in a section.
        min_tokens:     Minimum chunk size; tiny chunks are merged into neighbours.

    Returns:
        List of Chunk objects, deterministic for the same input.
    """
    if raw_json:
        items = _items_from_docling_json(raw_json)
    elif pages:
        items = _items_from_pages(pages)
    else:
        return []

    if not items:
        return []

    # Build ordered sections by heading path
    sections: List[_Section] = [_Section(heading_path=[])]
    current_path: List[str] = []

    for item in items:
        if item.item_type.startswith("heading"):
            level = item.level or 1
            # Update heading path: truncate deeper levels, replace at this level
            current_path = current_path[: level - 1] + [item.text]
            # Start a new section with this heading
            sections.append(_Section(heading_path=list(current_path)))
        else:
            sections[-1].items.append(item)

    # Convert sections → chunks
    all_chunks: List[Chunk] = []
    global_idx = 0

    for section in sections:
        if not section.items:
            continue

        text_buf: List[_Item] = []
        for item in section.items:
            if item.item_type == "table":
                # First flush any pending text
                if text_buf:
                    new_chunks = _flush_text_buffer(
                        text_buf,
                        section.heading_path,
                        doc_name,
                        global_idx,
                        max_tokens,
                        target_tokens,
                        overlap_tokens,
                        min_tokens,
                    )
                    # Re-index from global_idx
                    for c in new_chunks:
                        c.chunk_index = global_idx
                        global_idx += 1
                    all_chunks.extend(new_chunks)
                    text_buf = []

                # Handle table
                page_start = item.page_no
                page_end = item.page_no
                table_tokens = _count_tokens(item.text)
                if table_tokens <= max_tokens:
                    tcs = _make_single_chunk(
                        item.text, section.heading_path, page_start, page_end, doc_name, global_idx, "table"
                    )
                else:
                    tcs = _split_table_into_chunks(
                        item.text, section.heading_path, page_start, page_end, doc_name, global_idx, max_tokens
                    )
                for c in tcs:
                    c.chunk_index = global_idx
                    global_idx += 1
                all_chunks.extend(tcs)
            else:
                text_buf.append(item)

        # Flush remaining text
        if text_buf:
            new_chunks = _flush_text_buffer(
                text_buf,
                section.heading_path,
                doc_name,
                global_idx,
                max_tokens,
                target_tokens,
                overlap_tokens,
                min_tokens,
            )
            for c in new_chunks:
                c.chunk_index = global_idx
                global_idx += 1
            all_chunks.extend(new_chunks)

    # Merge tiny chunks into neighbours
    all_chunks = _merge_tiny_chunks(all_chunks, min_tokens, doc_name)

    # Final re-index to ensure sequential chunk_index
    for i, c in enumerate(all_chunks):
        c.chunk_index = i

    return all_chunks


def _merge_tiny_chunks(chunks: List[Chunk], min_tokens: int, doc_name: str) -> List[Chunk]:
    """Merge chunks below min_tokens into their adjacent neighbours (prefer next, fallback prev)."""
    if not chunks:
        return chunks

    merged = True
    while merged:
        merged = False
        result: List[Chunk] = []
        i = 0
        while i < len(chunks):
            c = chunks[i]
            if c.token_count < min_tokens and c.chunk_type not in ("table",):
                if i + 1 < len(chunks) and chunks[i + 1].chunk_type not in ("table",):
                    # Merge forward
                    nxt = chunks[i + 1]
                    merged_text = (c.text + "\n\n" + nxt.text).strip()
                    prefix = " > ".join(nxt.heading_path) if nxt.heading_path else ""
                    merged_embed = f"Document: {doc_name}" + (f" > {prefix}" if prefix else "") + "\n" + merged_text
                    new_c = Chunk(
                        chunk_index=c.chunk_index,
                        text=merged_text,
                        embed_text=merged_embed,
                        page_start=min(c.page_start, nxt.page_start),
                        page_end=max(c.page_end, nxt.page_end),
                        heading_path=nxt.heading_path,
                        chunk_type="mixed" if c.chunk_type != nxt.chunk_type else c.chunk_type,
                        token_count=_count_tokens(merged_text),
                    )
                    result.append(new_c)
                    i += 2
                    merged = True
                elif result and result[-1].chunk_type not in ("table",):
                    # Merge backward into last
                    prev = result.pop()
                    merged_text = (prev.text + "\n\n" + c.text).strip()
                    prefix = " > ".join(prev.heading_path) if prev.heading_path else ""
                    merged_embed = f"Document: {doc_name}" + (f" > {prefix}" if prefix else "") + "\n" + merged_text
                    new_c = Chunk(
                        chunk_index=prev.chunk_index,
                        text=merged_text,
                        embed_text=merged_embed,
                        page_start=min(prev.page_start, c.page_start),
                        page_end=max(prev.page_end, c.page_end),
                        heading_path=prev.heading_path,
                        chunk_type="mixed" if prev.chunk_type != c.chunk_type else prev.chunk_type,
                        token_count=_count_tokens(merged_text),
                    )
                    result.append(new_c)
                    i += 1
                    merged = True
                else:
                    result.append(c)
                    i += 1
            else:
                result.append(c)
                i += 1
        chunks = result

    return chunks
