import asyncio
import logging
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx

from app.config import settings
from app.services.parsers.base import (
    DocumentParser,
    DocumentParserError,
    ParsedDocument,
    ParsedPage,
    ParserUnavailableError,
)

logger = logging.getLogger(__name__)

DOCLING_PAGE_BREAK_MARKER = "<!-- DOCLING_PAGE_BREAK -->"


def _clean_plain_text(markdown_text: str) -> str:
    """Extract plain text from markdown by stripping headers, formatting, links, and table pipes."""
    if not markdown_text:
        return ""
    text = re.sub(r"<!--.*?-->", "", markdown_text, flags=re.DOTALL)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`{1,3}[^`]*`{1,3}", "", text)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"-{3,}", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return " ".join([l for l in lines if l])


def _check_page_quality_warnings(
    text: str,
    char_count: int,
    min_chars: int = 50,
) -> List[str]:
    """Heuristic quality checks for parsed page content."""
    warnings: List[str] = []
    if char_count < min_chars:
        warnings.append("low_text")

    # Garbled text heuristic: high ratio of non-ASCII / non-printable symbols
    if char_count > 20:
        alphanumeric_count = sum(1 for c in text if c.isalnum() or c.isspace())
        ratio = alphanumeric_count / char_count
        if ratio < 0.65:
            warnings.append("garbled")

    return warnings


class DoclingClientParser(DocumentParser):
    """
    Client for docling-serve REST API.
    Sends files, manages transient retries with exponential backoff,
    batches page ranges to constrain memory, and maps responses into ParsedDocument.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.DOCLING_URL).rstrip("/")
        self.parser_name = "docling"
        self.parser_version = "1.38.2"

    async def _post_convert_with_retry(
        self,
        file_path: Path,
        data_fields: Dict[str, Any],
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        """Post file to docling-serve with retries for transient errors and immediate failure on 4xx."""
        url = f"{self.base_url}/v1/convert/file"
        max_attempts = 3
        backoff_delay = 1.0
        client_timeout = httpx.Timeout(
            timeout=float(timeout_seconds),
            connect=min(15.0, float(timeout_seconds)),
        )

        for attempt in range(1, max_attempts + 1):
            try:
                file_bytes = file_path.read_bytes()
                async with httpx.AsyncClient(timeout=client_timeout) as client:
                    files = [("files", (file_path.name, file_bytes, "application/pdf"))]
                    response = await client.post(url, files=files, data=data_fields)

                    if response.status_code == 200:
                        return response.json()

                    # 4xx client errors should not be retried
                    if 400 <= response.status_code < 500:
                        error_detail = response.text[:400]
                        logger.error(
                            "Docling client error (HTTP %d): %s",
                            response.status_code,
                            error_detail,
                        )
                        raise DocumentParserError(
                            f"Docling conversion rejected (HTTP {response.status_code}): {error_detail}"
                        )

                    # 5xx server errors
                    logger.warning(
                        "Docling server error (HTTP %d) on attempt %d/%d: %s",
                        response.status_code,
                        attempt,
                        max_attempts,
                        response.text[:200],
                    )

            except (httpx.ConnectError, httpx.ConnectTimeout) as ce:
                logger.warning(
                    "Docling connection failure on attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    ce,
                )
                if attempt == max_attempts:
                    raise ParserUnavailableError("Parsing service unavailable") from ce

            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as te:
                logger.warning(
                    "Docling request timeout on attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    te,
                )
                if attempt == max_attempts:
                    raise DocumentParserError("Parsing request timed out") from te

            except (DocumentParserError, ParserUnavailableError):
                raise

            except Exception as e:
                logger.warning(
                    "Unexpected error communicating with Docling on attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    e,
                )
                if attempt == max_attempts:
                    raise DocumentParserError(f"Failed to communicate with Docling: {e}") from e

            # Exponential backoff
            if attempt < max_attempts:
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0

        raise DocumentParserError("Exhausted retries connecting to Docling service.")

    async def parse_single_batch(
        self,
        file_path: Path,
        start_page: int,
        end_page: int,
        options: Dict[str, Any],
    ) -> Tuple[List[ParsedPage], Optional[Dict[str, Any]]]:
        """Convert a specific slice of pages using Docling REST API."""
        do_ocr = options.get("do_ocr", settings.PARSE_OCR_ENABLED)
        timeout_seconds = options.get("timeout_seconds", settings.PARSE_TIMEOUT_SECONDS)
        min_chars = options.get("min_chars_per_page", settings.PARSE_MIN_CHARS_PER_PAGE)

        data_fields: Dict[str, Any] = {
            "to_formats": ["md", "json"],
            "do_table_structure": True,
            "include_images": False,
            "do_ocr": bool(do_ocr),
            "md_page_break_placeholder": DOCLING_PAGE_BREAK_MARKER,
            "page_range": [start_page, end_page],
        }

        resp = await self._post_convert_with_retry(
            file_path=file_path,
            data_fields=data_fields,
            timeout_seconds=timeout_seconds,
        )

        doc_data = resp.get("document", {})
        raw_md = doc_data.get("md_content", "") or ""
        json_content = doc_data.get("json_content", {})

        # Split markdown into per-page segments
        page_md_chunks = raw_md.split(DOCLING_PAGE_BREAK_MARKER)

        # Build lookup of tables and pictures per page from provenance
        tables_per_page = set()
        for t in json_content.get("tables", []):
            for pr in t.get("prov", []):
                p_no = pr.get("page_no")
                if p_no is not None:
                    tables_per_page.add(p_no)

        figures_per_page = set()
        for p in json_content.get("pictures", []):
            for pr in p.get("prov", []):
                p_no = pr.get("page_no")
                if p_no is not None:
                    figures_per_page.add(p_no)

        parsed_pages: List[ParsedPage] = []
        expected_page_count = (end_page - start_page) + 1

        for idx in range(expected_page_count):
            current_page_no = start_page + idx
            page_md = page_md_chunks[idx].strip() if idx < len(page_md_chunks) else ""
            plain = _clean_plain_text(page_md)
            char_count = len(plain)

            has_tbl = current_page_no in tables_per_page
            has_fig = current_page_no in figures_per_page

            warnings = _check_page_quality_warnings(
                text=plain,
                char_count=char_count,
                min_chars=min_chars,
            )

            parsed_pages.append(
                ParsedPage(
                    page_no=current_page_no,
                    markdown=page_md,
                    plain_text=plain,
                    char_count=char_count,
                    has_table=has_tbl,
                    has_figure=has_fig,
                    ocr_used=bool(do_ocr),
                    warnings=warnings,
                )
            )

        return parsed_pages, json_content

    async def parse(
        self,
        file_path: Path,
        options: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        """
        Parse complete PDF into structured pages.
        Batches requests by PARSE_BATCH_PAGES to bound memory consumption on large files.
        """
        opts = dict(options or {})
        batch_size = opts.get("batch_pages", settings.PARSE_BATCH_PAGES)
        progress_cb: Optional[Callable[[int, int], None]] = opts.get("on_progress")

        # Determine total page count via pypdf first
        from pypdf import PdfReader
        try:
            reader = PdfReader(str(file_path))
            total_pages = len(reader.pages)
        except Exception as e:
            raise DocumentParserError(f"Could not read PDF page count: {e}") from e

        if total_pages <= 0:
            raise DocumentParserError("PDF contains 0 pages.")

        all_pages: List[ParsedPage] = []
        raw_json_payloads: List[Dict[str, Any]] = []

        curr_start = 1
        while curr_start <= total_pages:
            curr_end = min(curr_start + batch_size - 1, total_pages)
            logger.info(
                "Parsing %s pages [%d to %d] of %d via Docling...",
                file_path.name,
                curr_start,
                curr_end,
                total_pages,
            )

            batch_pages, batch_json = await self.parse_single_batch(
                file_path=file_path,
                start_page=curr_start,
                end_page=curr_end,
                options=opts,
            )

            all_pages.extend(batch_pages)
            if batch_json:
                raw_json_payloads.append(batch_json)

            if progress_cb:
                try:
                    progress_cb(len(all_pages), total_pages)
                except Exception as cb_err:
                    logger.warning("Progress callback error: %s", cb_err)

            curr_start = curr_end + 1

        # Strict page count consistency check
        if len(all_pages) != total_pages:
            raise DocumentParserError(
                f"Parser page count mismatch: pypdf detected {total_pages} pages, but parser produced {len(all_pages)} pages."
            )

        # Concatenate full document markdown
        full_markdown = "\n\n".join(
            f"<!-- Page {p.page_no} -->\n{p.markdown}" for p in all_pages
        )

        return ParsedDocument(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            page_count=total_pages,
            pages=all_pages,
            raw_json=raw_json_payloads[0] if len(raw_json_payloads) == 1 else {"batches": raw_json_payloads},
            full_markdown=full_markdown,
        )
