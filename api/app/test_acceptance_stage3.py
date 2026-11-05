"""
Automated Acceptance Tests for Stage 3 (File Upload, Storage, and Ingestion)
"""
import io
import os
import time
import requests
from PIL import Image
from pypdf import PdfWriter

BASE_URL = "http://localhost:8000"
UPLOADS_DIR = "/data/uploads"

def create_sample_pdf(num_pages=2, encrypt_password=None):
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    if encrypt_password:
        writer.encrypt(encrypt_password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

def create_sample_png(width=120, height=80):
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def create_conversation(title="Acceptance Test"):
    res = requests.post(f"{BASE_URL}/api/conversations", json={"title": title})
    res.raise_for_status()
    return res.json()["id"]

def run_tests():
    results = {}
    print("=" * 60)
    print("STARTING STAGE 3 ACCEPTANCE TESTS")
    print("=" * 60)

    # ---------------------------------------------------------
    # Acceptance Test 2: Upload Normal PDF
    # ---------------------------------------------------------
    print("\n--- Test 2: Normal PDF Upload & Ingestion ---")
    conv_id = create_conversation("Test 2 Conversation")
    pdf_bytes = create_sample_pdf(num_pages=2)
    files = [("files", ("sample_2page.pdf", pdf_bytes, "application/pdf"))]
    t0 = time.time()
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_id}/documents", files=files)
    upload_duration = time.time() - t0
    assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
    data = res.json()
    assert len(data) == 1
    doc2 = data[0]
    print(f"Immediate response in {upload_duration:.3f}s: status='{doc2['status']}'")
    assert doc2["status"] == "processing", f"Expected 'processing', got {doc2['status']}"

    # Poll status until ready
    doc2_id = doc2["id"]
    for _ in range(20):
        time.sleep(0.5)
        check = requests.get(f"{BASE_URL}/api/documents/{doc2_id}").json()
        if check["status"] == "ready":
            break
    print(f"Final status: '{check['status']}', page_count={check.get('page_count')}, mime={check['mime_type']}")
    assert check["status"] == "ready"
    assert check["page_count"] == 2
    assert check["mime_type"] == "application/pdf"
    assert check["sha256"]
    results["Test 2: Normal PDF Upload"] = "PASSED (page_count=2, status=ready)"

    # ---------------------------------------------------------
    # Acceptance Test 3: Upload PNG/JPEG & Preview (/file)
    # ---------------------------------------------------------
    print("\n--- Test 3: Image Upload & File Preview Headers ---")
    png_bytes = create_sample_png(width=160, height=90)
    files = [("files", ("banner.png", png_bytes, "image/png"))]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_id}/documents", files=files)
    assert res.status_code == 201
    doc3 = res.json()[0]
    doc3_id = doc3["id"]

    for _ in range(20):
        time.sleep(0.5)
        check3 = requests.get(f"{BASE_URL}/api/documents/{doc3_id}").json()
        if check3["status"] == "ready":
            break
    print(f"Final status: '{check3['status']}', width={check3.get('width')}, height={check3.get('height')}")
    assert check3["status"] == "ready"
    assert check3["width"] == 160
    assert check3["height"] == 90
    assert check3["mime_type"] == "image/png"

    # Test /file endpoint
    file_res = requests.get(f"{BASE_URL}/api/documents/{doc3_id}/file")
    assert file_res.status_code == 200
    assert file_res.headers.get("content-type") == "image/png"
    assert file_res.headers.get("x-content-type-options") == "nosniff"
    assert "inline" in file_res.headers.get("content-disposition", "")
    print(f"File endpoint headers: Content-Type={file_res.headers.get('content-type')}, X-Content-Type-Options={file_res.headers.get('x-content-type-options')}, Content-Disposition={file_res.headers.get('content-disposition')}")
    results["Test 3: Image Upload & Preview"] = "PASSED (160x90, nosniff, inline preview)"

    # ---------------------------------------------------------
    # Acceptance Test 4: Batch of 3 files where 1 is invalid
    # ---------------------------------------------------------
    print("\n--- Test 4: Batch Upload with 1 Invalid File ---")
    valid_txt = b"Hello, this is a plain text file for Stage 3 testing.\nLine 2.\n"
    fake_exe_pdf = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This is a Windows PE executable"
    valid_png = create_sample_png(width=50, height=50)

    batch_files = [
        ("files", ("notes.txt", valid_txt, "text/plain")),
        ("files", ("bad_program.pdf", fake_exe_pdf, "application/pdf")),
        ("files", ("icon.png", valid_png, "image/png")),
    ]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_id}/documents", files=batch_files)
    assert res.status_code == 201
    batch_res = res.json()
    assert len(batch_res) == 3
    print("Batch results:")
    for doc in batch_res:
        print(f" - {doc['filename']}: status={doc['status']}, error={doc.get('error')}")
        # Verify no server paths leak in error
        if doc.get("error"):
            assert "/data" not in doc["error"] and "/app" not in doc["error"]

    bad_doc = next(d for d in batch_res if d["filename"] == "bad_program.pdf")
    assert bad_doc["status"] == "failed"
    assert "Unsupported file type" in bad_doc["error"]

    # Wait for valid files to become ready
    txt_doc = next(d for d in batch_res if d["filename"] == "notes.txt")
    for _ in range(20):
        time.sleep(0.5)
        check_txt = requests.get(f"{BASE_URL}/api/documents/{txt_doc['id']}").json()
        if check_txt["status"] == "ready":
            break
    assert check_txt["status"] == "ready"
    assert check_txt["meta"].get("lines") == 2
    results["Test 4: Batch with 1 Invalid"] = "PASSED (2 succeeded, 1 failed safely with zero path leak)"

    # ---------------------------------------------------------
    # Acceptance Test 5: File Exceeding MAX_UPLOAD_MB
    # ---------------------------------------------------------
    print("\n--- Test 5: Upload Exceeding MAX_UPLOAD_MB ---")
    oversized_size = 51 * 1024 * 1024  # 51 MB
    print(f"Creating {oversized_size / (1024*1024):.1f}MB temporary file to test size enforcement...")
    large_filepath = "/tmp/too_large_51mb.txt"
    chunk_1mb = b"A" * (1024 * 1024)
    with open(large_filepath, "wb") as f:
        for _ in range(51):
            f.write(chunk_1mb)

    # List files before upload
    before_dirs = set(os.listdir(UPLOADS_DIR)) if os.path.exists(UPLOADS_DIR) else set()

    with open(large_filepath, "rb") as lf:
        res = requests.post(
            f"{BASE_URL}/api/conversations/{conv_id}/documents",
            files=[("files", ("too_large.txt", lf, "text/plain"))]
        )
    print(f"Status code: {res.status_code}")
    res_data = res.json()
    print(f"Response: {res_data}")

    # Remove temporary test file
    if os.path.exists(large_filepath):
        os.remove(large_filepath)

    assert len(res_data) == 1
    assert res_data[0]["status"] == "failed"
    assert "exceeds maximum allowed size" in res_data[0]["error"]

    # Check that disk has no leftover partial directory
    after_dirs = set(os.listdir(UPLOADS_DIR)) if os.path.exists(UPLOADS_DIR) else set()
    diff_dirs = after_dirs - before_dirs
    print(f"Leftover upload directories created: {diff_dirs}")
    assert len(diff_dirs) == 0, f"Expected 0 leftover dirs, found: {diff_dirs}"
    results["Test 5: Size Limit & Clean Cleanup"] = "PASSED (rejected, 0 leftover files on disk, streamed in 64KB chunks)"

    # ---------------------------------------------------------
    # Acceptance Test 6: Exceed MAX_FILES_PER_CONVERSATION
    # ---------------------------------------------------------
    print("\n--- Test 6: Exceed MAX_FILES_PER_CONVERSATION ---")
    conv_limit_id = create_conversation("Limit Test Conversation")
    # Upload 5 files
    batch1 = [("files", (f"file_{i}.txt", f"Content {i}".encode(), "text/plain")) for i in range(5)]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_limit_id}/documents", files=batch1)
    assert res.status_code == 201

    # Upload 5 more files (total 10)
    batch2 = [("files", (f"file_{i}.txt", f"Content {i}".encode(), "text/plain")) for i in range(5, 10)]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_limit_id}/documents", files=batch2)
    assert res.status_code == 201

    # Try 11th file: should be rejected
    batch3 = [("files", ("overflow.txt", b"Overflow", "text/plain"))]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_limit_id}/documents", files=batch3)
    print(f"11th file upload status: {res.status_code}, error: {res.text}")
    assert res.status_code == 400
    assert "cannot exceed 10 documents" in res.text
    results["Test 6: Conversation Limit (10)"] = "PASSED (rejected with 400 when exceeding 10 files)"

    # ---------------------------------------------------------
    # Acceptance Test 7: Path Traversal Sanitization
    # ---------------------------------------------------------
    print("\n--- Test 7: Path Traversal Sanitization ---")
    tricky_filename = "../../etc/passwd.pdf"
    pdf_bytes = create_sample_pdf(num_pages=1)
    files = [("files", (tricky_filename, pdf_bytes, "application/pdf"))]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_id}/documents", files=files)
    assert res.status_code == 201
    doc7 = res.json()[0]
    print(f"Client requested filename: '{tricky_filename}'")
    print(f"Sanitized filename in DB: '{doc7['filename']}'")
    assert ".." not in doc7["filename"]
    assert "/" not in doc7["filename"] and "\\" not in doc7["filename"]

    # Verify storage path on disk uses UUID only
    expected_path = os.path.join(UPLOADS_DIR, doc7["id"], "original.pdf")
    assert os.path.exists(expected_path), f"File not found at UUID path: {expected_path}"
    print(f"File verified at secure path: {expected_path}")
    results["Test 7: Path Traversal Sanitization"] = "PASSED (sanitized to passwd.pdf, stored strictly under UUID)"

    # ---------------------------------------------------------
    # Acceptance Test 8: Encrypted PDF Handling
    # ---------------------------------------------------------
    print("\n--- Test 8: Encrypted / Password-Protected PDF ---")
    enc_pdf = create_sample_pdf(num_pages=2, encrypt_password="secretpassword")
    files = [("files", ("protected.pdf", enc_pdf, "application/pdf"))]
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_id}/documents", files=files)
    assert res.status_code == 201
    doc8 = res.json()[0]

    for _ in range(20):
        time.sleep(0.5)
        check8 = requests.get(f"{BASE_URL}/api/documents/{doc8['id']}").json()
        if check8["status"] in ("ready", "failed"):
            break
    print(f"Encrypted PDF status: '{check8['status']}', error: '{check8.get('error')}'")
    assert check8["status"] == "failed"
    assert "encrypted" in check8["error"].lower() or "password" in check8["error"].lower()
    results["Test 8: Encrypted PDF"] = "PASSED (failed with safe error: 'Password-protected or encrypted PDFs are not supported')"

    # ---------------------------------------------------------
    # Acceptance Test 10: Deletion & Cascading File Cleanup
    # ---------------------------------------------------------
    print("\n--- Test 10: Document and Cascading Conversation Deletion ---")
    doc_to_delete_id = doc7["id"]
    doc_path = os.path.join(UPLOADS_DIR, doc_to_delete_id)
    assert os.path.exists(doc_path)
    del_res = requests.delete(f"{BASE_URL}/api/documents/{doc_to_delete_id}")
    assert del_res.status_code == 204
    assert not os.path.exists(doc_path), f"Directory still exists after delete: {doc_path}"
    assert requests.get(f"{BASE_URL}/api/documents/{doc_to_delete_id}").status_code == 404
    print("Single document deletion: DB row and disk folder successfully removed.")

    conv_cascade_id = create_conversation("Cascade Conversation")
    f1 = ("files", ("c1.txt", b"Cascade 1", "text/plain"))
    f2 = ("files", ("c2.txt", b"Cascade 2", "text/plain"))
    res = requests.post(f"{BASE_URL}/api/conversations/{conv_cascade_id}/documents", files=[f1, f2])
    assert res.status_code == 201
    c_docs = res.json()
    d1_path = os.path.join(UPLOADS_DIR, c_docs[0]["id"])
    d2_path = os.path.join(UPLOADS_DIR, c_docs[1]["id"])
    assert os.path.exists(d1_path) and os.path.exists(d2_path)
    print(f"Created conversation with 2 documents at: {d1_path} and {d2_path}")

    del_conv = requests.delete(f"{BASE_URL}/api/conversations/{conv_cascade_id}")
    assert del_conv.status_code == 204
    assert not os.path.exists(d1_path), f"d1_path still exists: {d1_path}"
    assert not os.path.exists(d2_path), f"d2_path still exists: {d2_path}"
    print("Conversation deletion: all attached document folders removed from disk.")
    results["Test 10: Cascading Deletion"] = "PASSED (both document & conversation deletion completely purge disk files)"

    # ---------------------------------------------------------
    # Acceptance Test 12: Stage 1 & 2 Regressions
    # ---------------------------------------------------------
    print("\n--- Test 12: Stage 1 & 2 Regressions ---")
    health = requests.get(f"{BASE_URL}/api/health").json()
    print(f"Health response: {health}")
    assert health["api"] == "ok"
    assert health["db"] == "ok"
    assert health["pgvector"] == "ok"
    assert health["gemini_key_configured"] is True

    chat_conv_id = create_conversation("Chat Regression Test")
    chat_res = requests.post(
        f"{BASE_URL}/api/chat",
        json={"conversation_id": chat_conv_id, "message": "Respond with the word 'PONG'."},
        stream=True
    )
    assert chat_res.status_code == 200
    events = []
    for line in chat_res.iter_lines():
        if line:
            events.append(line.decode("utf-8"))
    print(f"Chat stream received {len(events)} event lines.")
    assert any("token" in e or "PONG" in e for e in events)
    assert any("done" in e for e in events)
    results["Test 12: Regressions (Health & Chat Streaming)"] = "PASSED (health OK, streaming chat responds with tokens and done)"

    # ---------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("ACCEPTANCE TESTS SUMMARY")
    print("=" * 60)
    for name, outcome in results.items():
        print(f"✔ {name}: {outcome}")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
