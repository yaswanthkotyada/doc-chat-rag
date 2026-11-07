"""
Unit tests for Citation Parser and StreamCitationBuffer.
"""
import uuid
import unittest
from app.services.citations import parse_and_validate_citations, StreamCitationBuffer


class FakeDocument:
    def __init__(self, id_str: str, filename: str, page_count: int = None):
        self.id = uuid.UUID(id_str)
        self.filename = filename
        self.page_count = page_count


class TestCitationParser(unittest.TestCase):
    def setUp(self):
        self.doc_contract = FakeDocument("11111111-1111-1111-1111-111111111111", "contract_v2.1.pdf", page_count=10)
        self.doc_image = FakeDocument("22222222-2222-2222-2222-222222222222", "system architecture chart (final).png")
        self.doc_text = FakeDocument("33333333-3333-3333-3333-333333333333", "notes-2024.txt")
        self.doc_dup1 = FakeDocument("44444444-4444-4444-4444-444444444444", "duplicate.pdf", page_count=5)
        self.doc_dup2 = FakeDocument("55555555-5555-5555-5555-555555555555", "duplicate.pdf", page_count=20)
        self.documents = [
            self.doc_contract,
            self.doc_image,
            self.doc_text,
            self.doc_dup1,
            self.doc_dup2,
        ]

    def test_valid_pdf_page_citation(self):
        text = "The warranty period is 2 years [[cite: contract_v2.1.pdf | p.4]]."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(cleaned, "The warranty period is 2 years [[cite: contract_v2.1.pdf | p.4]].")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["filename"], "contract_v2.1.pdf")
        self.assertEqual(citations[0]["page"], 4)
        self.assertEqual(citations[0]["document_id"], str(self.doc_contract.id))

    def test_valid_image_and_text_non_paged_citation(self):
        text = "Architecture shows 3 tiers [[cite: system architecture chart (final).png]], as noted in [[cite: notes-2024.txt]]."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(len(citations), 2)
        self.assertIn("[[cite: system architecture chart (final).png]]", cleaned)
        self.assertIn("[[cite: notes-2024.txt]]", cleaned)
        self.assertIsNone(citations[0]["page"])
        self.assertIsNone(citations[1]["page"])

    def test_out_of_bounds_page_drops_page_number(self):
        # contract_v2.1.pdf has only 10 pages; citing p.25 should drop page and keep file
        text = "Payment terms are net 30 [[cite: contract_v2.1.pdf | p.25]]."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(cleaned, "Payment terms are net 30 [[cite: contract_v2.1.pdf]].")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["filename"], "contract_v2.1.pdf")
        self.assertIsNone(citations[0]["page"])

    def test_unknown_filename_is_dropped_cleanly(self):
        text = "According to malicious.exe [[cite: virus.exe | p.1]], the sky is green."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(cleaned, "According to malicious.exe, the sky is green.")
        self.assertEqual(len(citations), 0)

    def test_multiple_citations_in_one_sentence(self):
        text = "Claim A [[cite: contract_v2.1.pdf | p.2]] and Claim B [[cite: notes-2024.txt]] agree."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(len(citations), 2)
        self.assertIn("[[cite: contract_v2.1.pdf | p.2]]", cleaned)
        self.assertIn("[[cite: notes-2024.txt]]", cleaned)

    def test_duplicate_filenames_disambiguation(self):
        # When 2 documents share the exact name, disambiguation selects the first candidate in list
        text = "Clause 9 applies [[cite: duplicate.pdf | p.3]]."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["document_id"], str(self.doc_dup1.id))
        self.assertEqual(citations[0]["page"], 3)

    def test_malformed_markers(self):
        # Missing closing brackets or malformed text should not crash
        text = "Unfinished marker [[cite: contract_v2.1.pdf | and another [[cite: contract_v2.1.pdf | p.1]]."
        cleaned, citations = parse_and_validate_citations(text, self.documents)

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["page"], 1)

    def test_stream_citation_buffer_split_across_chunks(self):
        buffer = StreamCitationBuffer()

        # Simulate chunks splitting [[cite: contract_v2.1.pdf | p.3]] across 3 tokens
        c1 = buffer.process_chunk("The total cost is $5,000 [[cite: con")
        c2 = buffer.process_chunk("tract_v2.1.pdf | ")
        c3 = buffer.process_chunk("p.3]] according to the terms.")
        c4 = buffer.flush()

        # During chunk 1 and 2, partial marker was held in buffer
        self.assertEqual(c1, "The total cost is $5,000 ")
        self.assertEqual(c2, "")
        self.assertEqual(c3, "[[cite: contract_v2.1.pdf | p.3]] according to the terms.")
        self.assertEqual(c4, "")

        reconstructed = c1 + c2 + c3 + c4
        self.assertEqual(reconstructed, "The total cost is $5,000 [[cite: contract_v2.1.pdf | p.3]] according to the terms.")


class FakeRegistryItem:
    def __init__(self, document_id, document_filename, page_start, page_end, chunk_id, chunk_index=0):
        self.document_id = document_id
        self.document_filename = document_filename
        self.page_start = page_start
        self.page_end = page_end
        self.chunk_id = chunk_id
        self.chunk_index = chunk_index


class TestRAGCitationResolution(unittest.TestCase):
    def setUp(self):
        self.doc_id1 = uuid.uuid4()
        self.doc_id2 = uuid.uuid4()
        self.chunk_id1 = uuid.uuid4()
        self.chunk_id2 = uuid.uuid4()
        self.chunk_id3 = uuid.uuid4()

        self.documents = [
            FakeDocument(str(self.doc_id1), "manual.pdf", page_count=50),
            FakeDocument(str(self.doc_id2), "spec.pdf", page_count=25),
        ]

        self.registry = {
            "R1": FakeRegistryItem(self.doc_id1, "manual.pdf", page_start=5, page_end=5, chunk_id=self.chunk_id1),
            "R2": FakeRegistryItem(self.doc_id1, "manual.pdf", page_start=12, page_end=15, chunk_id=self.chunk_id2),
            "R3": FakeRegistryItem(self.doc_id2, "spec.pdf", page_start=20, page_end=20, chunk_id=self.chunk_id3),
        }

    def test_rag_single_page_citation(self):
        text = "The system starts up in 10 seconds [cite: R1]."
        cleaned, citations = parse_and_validate_citations(text, self.documents, result_registry=self.registry)

        self.assertEqual(cleaned, "The system starts up in 10 seconds [[cite: manual.pdf | p.5]].")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["filename"], "manual.pdf")
        self.assertEqual(citations[0]["page"], 5)
        self.assertEqual(citations[0]["page_end"], 5)
        self.assertEqual(citations[0]["chunk_id"], str(self.chunk_id1))

    def test_rag_page_range_citation(self):
        text = "Detailed wiring diagrams are provided [cite: R2]."
        cleaned, citations = parse_and_validate_citations(text, self.documents, result_registry=self.registry)

        self.assertEqual(cleaned, "Detailed wiring diagrams are provided [[cite: manual.pdf | p.12-15]].")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["page"], 12)
        self.assertEqual(citations[0]["page_end"], 15)
        self.assertEqual(citations[0]["chunk_id"], str(self.chunk_id2))

    def test_rag_multiple_comma_separated_ids(self):
        text = "Both manuals specify redundant power supplies [cite: R1, R3]."
        cleaned, citations = parse_and_validate_citations(text, self.documents, result_registry=self.registry)

        self.assertIn("[[cite: manual.pdf | p.5]]", cleaned)
        self.assertIn("[[cite: spec.pdf | p.20]]", cleaned)
        self.assertEqual(len(citations), 2)

    def test_rag_double_brackets_supported(self):
        text = "Operational temperature is -20C to +60C [[cite: R1]]."
        cleaned, citations = parse_and_validate_citations(text, self.documents, result_registry=self.registry)

        self.assertEqual(cleaned, "Operational temperature is -20C to +60C [[cite: manual.pdf | p.5]].")
        self.assertEqual(len(citations), 1)

    def test_rag_unknown_or_invented_id_dropped(self):
        text = "Unverified claim from an invented chunk [cite: R99]."
        cleaned, citations = parse_and_validate_citations(text, self.documents, result_registry=self.registry)

        self.assertEqual(cleaned, "Unverified claim from an invented chunk.")
        self.assertEqual(len(citations), 0)

    def test_mixed_mode_citations(self):
        direct_doc = FakeDocument("66666666-6666-6666-6666-666666666666", "direct_note.pdf", page_count=10)
        docs = self.documents + [direct_doc]

        text = "Direct claim [[cite: direct_note.pdf | p.3]] combined with RAG claim [cite: R3]."
        cleaned, citations = parse_and_validate_citations(text, docs, result_registry=self.registry)

        self.assertIn("[[cite: direct_note.pdf | p.3]]", cleaned)
        self.assertIn("[[cite: spec.pdf | p.20]]", cleaned)
        self.assertEqual(len(citations), 2)
        filenames = {c["filename"] for c in citations}
        self.assertEqual(filenames, {"direct_note.pdf", "spec.pdf"})


if __name__ == "__main__":
    unittest.main()

