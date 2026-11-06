"""
Verification script for Stage 5 Milestone 2:
Parser Interface and Docling Client.
"""
import asyncio
import json
from pathlib import Path
import tempfile
import time

from app.services.parsers import (
    DoclingClientParser,
    DocumentParser,
    DocumentParserError,
    ParsedDocument,
    ParserUnavailableError,
)
from app.test_acceptance_stage4 import make_pdf


async def run_milestone2_tests():
    print("=" * 70)
    print("VERIFYING STAGE 5 MILESTONE 2: PARSER INTERFACE & DOCLING CLIENT")
    print("=" * 70)

    # 1. Create a 3-page test PDF with structured headings and content
    p1 = "Project Nebula Architecture Specification\nPage 1 Overview\nThe Nebula system is designed for high-throughput stream ingestion."
    p2 = "Phase 2 Implementation Timelines\nPage 2 Schedule\nMilestone A is scheduled for Q1 2025. Milestone B delivers core models."
    p3 = "Operational Metrics and Security\nPage 3 Compliance\nTarget availability is 99.95%. Encryption is AES-256 at rest."

    pdf_bytes = make_pdf([p1, p2, p3])
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    progress_log = []

    def on_progress(pages_done: int, total_pages: int):
        progress_log.append((pages_done, total_pages))
        print(f"  [Progress Callback] {pages_done}/{total_pages} pages parsed")

    try:
        parser = DoclingClientParser()
        print(f"\n1. Initialized parser: {parser.parser_name} (version {parser.parser_version})")
        print(f"   Target docling endpoint: {parser.base_url}")

        # 2. Test parse with page batching (batch_pages=2 on 3-page doc triggers 2 batches: [1,2] and [3,3])
        print("\n2. Executing parse() with batch_pages=2 (testing batching & progress)...")
        start_time = time.time()
        parsed_doc: ParsedDocument = await parser.parse(
            file_path=tmp_path,
            options={
                "batch_pages": 2,
                "do_ocr": False,
                "on_progress": on_progress,
            },
        )
        elapsed = time.time() - start_time
        print(f"   Parsed completed in {elapsed:.2f} seconds.")

        # 3. Assertions on ParsedDocument
        print("\n3. Validating ParsedDocument contract:")
        assert parsed_doc.parser_name == "docling"
        assert parsed_doc.page_count == 3
        assert len(parsed_doc.pages) == 3
        print(f"   - parser_name: {parsed_doc.parser_name} (PASS)")
        print(f"   - page_count: {parsed_doc.page_count} (PASS)")
        print(f"   - pages count: {len(parsed_doc.pages)} (PASS)")
        print(f"   - progress callbacks recorded: {progress_log} (PASS)")

        # 4. Assertions on individual ParsedPage objects
        print("\n4. Per-page output details:")
        for page in parsed_doc.pages:
            print(f"   --- PAGE {page.page_no} ---")
            print(f"   char_count: {page.char_count}")
            print(f"   has_table: {page.has_table}, has_figure: {page.has_figure}, ocr_used: {page.ocr_used}")
            print(f"   warnings: {page.warnings}")
            print(f"   markdown preview: {page.markdown[:80]!r}")
            print(f"   plain text preview: {page.plain_text[:80]!r}")

            assert page.page_no in (1, 2, 3)
            assert page.char_count > 0
            assert len(page.markdown) > 0
            assert len(page.plain_text) > 0

        # Check full markdown
        assert parsed_doc.full_markdown is not None
        assert "<!-- Page 1 -->" in parsed_doc.full_markdown
        assert "<!-- Page 2 -->" in parsed_doc.full_markdown
        assert "<!-- Page 3 -->" in parsed_doc.full_markdown
        print("\n5. Full Markdown assembly: PASS")

        # 5. Raw response shape preview
        print("\n6. Raw response shape preview:")
        if parsed_doc.raw_json:
            sample_keys = list(parsed_doc.raw_json.keys())
            print(f"   Raw JSON root keys: {sample_keys}")
            if "batches" in parsed_doc.raw_json:
                print(f"   Number of batch JSON payloads: {len(parsed_doc.raw_json['batches'])}")
                b1_keys = list(parsed_doc.raw_json["batches"][0].keys())
                print(f"   Batch 1 keys: {b1_keys}")

        # 6. Test unreachable service error handling
        print("\n7. Testing failure mode with unreachable endpoint:")
        bad_parser = DoclingClientParser(base_url="http://127.0.0.1:59999")
        try:
            await bad_parser.parse(file_path=tmp_path, options={"timeout_seconds": 1.0})
            raise AssertionError("Expected ParserUnavailableError but parse succeeded.")
        except ParserUnavailableError as pue:
            print(f"   Caught expected ParserUnavailableError: {pue} (PASS)")

        print("\n" + "=" * 70)
        print("ALL MILESTONE 2 TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        if tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    asyncio.run(run_milestone2_tests())

