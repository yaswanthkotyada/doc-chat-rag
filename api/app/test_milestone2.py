"""
Automated Verification for Milestone 2 (LLM Service File Parts & Gemini Caching)
"""
import asyncio
from datetime import datetime, timedelta, timezone
import io
import os
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select

from app.db import async_session_factory
from app.models.conversation import Conversation
from app.models.document import Document
from app.services.llm import llm_service
from app.services.storage import save_upload_stream

async def test_milestone2():
    print("=" * 60)
    print("TESTING MILESTONE 2: LLM SERVICE FILE PARTS & GEMINI CACHING")
    print("=" * 60)

    async with async_session_factory() as db:
        conv = Conversation(title="Milestone 2 Test")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

        # 1. Create and save a small 2-page PDF
        w = PdfWriter()
        p1 = w.add_blank_page(width=200, height=200)
        p2 = w.add_blank_page(width=200, height=200)
        pdf_buf = io.BytesIO()
        w.write(pdf_buf)
        pdf_bytes = pdf_buf.getvalue()

        doc_pdf = Document(
            conversation_id=conv.id,
            filename="financial_summary.pdf",
            mime_type="application/pdf",
            size_bytes=len(pdf_bytes),
            sha256="fake_sha",
            status="ready",
            page_count=2,
            mode="direct"
        )
        db.add(doc_pdf)
        await db.commit()
        await db.refresh(doc_pdf)

        # Save to disk
        from app.services.storage import get_document_dir, get_document_file_path
        doc_dir = get_document_dir(doc_pdf.id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = get_document_file_path(doc_pdf.id, doc_pdf.mime_type)
        pdf_path.write_bytes(pdf_bytes)

        # 2. Test ensure_gemini_file upload and caching
        print("\n--- Test 2.1: First upload to Gemini Files API ---")
        part1 = await llm_service.ensure_gemini_file(doc_pdf, db)
        await db.refresh(doc_pdf)

        meta1 = doc_pdf.meta or {}
        print("Cached meta after upload:", meta1)
        assert meta1.get("gemini_file_name"), "Missing gemini_file_name in meta"
        assert meta1.get("gemini_file_uri"), "Missing gemini_file_uri in meta"
        assert meta1.get("gemini_file_expires_at"), "Missing gemini_file_expires_at in meta"
        first_uri = meta1["gemini_file_uri"]
        print(f"First upload success: file_name={meta1['gemini_file_name']}")

        # 3. Test caching: call ensure_gemini_file again, must reuse same URI without upload
        print("\n--- Test 2.2: Cache hit verification ---")
        part2 = await llm_service.ensure_gemini_file(doc_pdf, db)
        assert part2.file_data.file_uri == first_uri, "Expected reused file URI from cache"
        print("Cache hit confirmed: reused cached Gemini file URI successfully.")

        # 4. Test expiry refresh: set gemini_file_expires_at to the past
        print("\n--- Test 2.3: Cache expiration & transparent re-upload ---")
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        doc_pdf.meta = {**meta1, "gemini_file_expires_at": expired_time}
        await db.commit()
        await db.refresh(doc_pdf)

        part3 = await llm_service.ensure_gemini_file(doc_pdf, db)
        await db.refresh(doc_pdf)
        meta3 = doc_pdf.meta or {}
        print("Meta after re-upload:", meta3)
        assert meta3["gemini_file_expires_at"] > datetime.now(timezone.utc).isoformat(), "Expiration time not refreshed"
        print("Expiration detected: re-upload succeeded and refreshed expiration time.")

        # 5. Create an image and CSV document
        img = Image.new("RGB", (80, 80), color="blue")
        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_bytes = img_buf.getvalue()

        doc_img = Document(
            conversation_id=conv.id,
            filename="chart.png",
            mime_type="image/png",
            size_bytes=len(img_bytes),
            sha256="fake_img_sha",
            status="ready",
            width=80,
            height=80,
            mode="direct"
        )
        db.add(doc_img)
        await db.commit()
        await db.refresh(doc_img)
        img_dir = get_document_dir(doc_img.id)
        img_dir.mkdir(parents=True, exist_ok=True)
        get_document_file_path(doc_img.id, doc_img.mime_type).write_bytes(img_bytes)

        # CSV with 10 rows
        csv_text = "id,name,value\n" + "".join([f"{i},Item {i},{i*10}\n" for i in range(1, 10)])
        csv_bytes = csv_text.encode("utf-8")
        doc_csv = Document(
            conversation_id=conv.id,
            filename="data.csv",
            mime_type="text/csv",
            size_bytes=len(csv_bytes),
            sha256="fake_csv_sha",
            status="ready",
            mode="direct",
            meta={"lines": 10, "characters": len(csv_text)}
        )
        db.add(doc_csv)
        await db.commit()
        await db.refresh(doc_csv)
        csv_dir = get_document_dir(doc_csv.id)
        csv_dir.mkdir(parents=True, exist_ok=True)
        get_document_file_path(doc_csv.id, doc_csv.mime_type).write_bytes(csv_bytes)

        # 6. Test build_document_parts
        print("\n--- Test 2.4: Building document parts ---")
        parts = await llm_service.build_document_parts([doc_pdf, doc_img, doc_csv], db)
        print(f"Built {len(parts)} multimodal parts:")
        for idx, p in enumerate(parts):
            p_type = "text" if p.text else ("file_uri" if p.file_data else ("inline_bytes" if p.inline_data else "other"))
            preview = (p.text[:40] + "...") if p.text else (p.file_data.file_uri if p.file_data else f"bytes len={len(p.inline_data.data)}")
            print(f"  Part {idx}: type={p_type}, preview={preview}")
        assert len(parts) >= 5, f"Expected at least 5 parts (labels + contents), got {len(parts)}"

        # 7. Test stream_chat with attached_parts and usage_collector
        print("\n--- Test 2.5: Streaming chat with attached parts & token usage ---")
        usage = {}
        stream = llm_service.stream_chat(
            system_instruction="You are a helpful document assistant. Answer in one sentence.",
            messages=[{"role": "user", "content": "What files did I provide?"}],
            attached_parts=parts,
            usage_collector=usage
        )

        chunks = []
        async for chunk in stream:
            chunks.append(chunk)

        full_reply = "".join(chunks)
        print("Model Reply:", full_reply.strip())
        print("Collected Usage:", usage)

        assert full_reply, "Model reply was empty"
        assert "prompt_tokens" in usage and usage["prompt_tokens"] > 0, f"Expected prompt_tokens, got: {usage}"
        assert "candidates_tokens" in usage and usage["candidates_tokens"] > 0, f"Expected candidates_tokens, got: {usage}"
        assert "total_tokens" in usage and usage["total_tokens"] > 0, f"Expected total_tokens, got: {usage}"

    print("\n" + "=" * 60)
    print("ALL MILESTONE 2 TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_milestone2())
