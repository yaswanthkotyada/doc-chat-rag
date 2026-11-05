"""
Verification Script for Milestone 3 (Grounded Prompt & Chat Endpoint Integration)
"""
import io
import requests
import time
from pypdf import PdfWriter

BASE_URL = "http://localhost:8000"

def run_tests():
    print("=" * 60)
    print("TESTING MILESTONE 3: GROUNDED PROMPT & CHAT INTEGRATION")
    print("=" * 60)

    # 1. Plain chat with no documents (Stage 2 behavior preserved)
    print("\n--- Test 3.1: Plain Chat without Documents ---")
    c1 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Plain Chat"}).json()
    cid1 = c1["id"]
    res1 = requests.post(
        f"{BASE_URL}/api/chat",
        json={"conversation_id": cid1, "message": "Reply with 'Stage 2 works'."},
        stream=True
    )
    assert res1.status_code == 200
    lines1 = [line.decode("utf-8") for line in res1.iter_lines() if line]
    print(f"Plain chat received {len(lines1)} lines.")
    assert any("token" in l for l in lines1)
    assert any("done" in l for l in lines1)
    print("Plain chat passed.")

    # 2. Document upload and grounded QA
    print("\n--- Test 3.2: Grounded Chat with Attached Document ---")
    c2 = requests.post(f"{BASE_URL}/api/conversations", json={"title": "Grounded Chat"}).json()
    cid2 = c2["id"]

    secret_note = b"Project Antigravity Confidential Note:\nThe secret access code is DELTA-99.\nThe project manager is Dr. Katherine Johnson.\n"
    up_res = requests.post(
        f"{BASE_URL}/api/conversations/{cid2}/documents",
        files=[("files", ("secret.txt", secret_note, "text/plain"))]
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()[0]["id"]

    # Wait for ready status
    for _ in range(10):
        time.sleep(0.5)
        d = requests.get(f"{BASE_URL}/api/documents/{doc_id}").json()
        if d["status"] == "ready":
            break
    print(f"Document status: {d['status']}, mode: {d['mode']}")
    assert d["mode"] == "direct"

    # Ask question using the document
    res2 = requests.post(
        f"{BASE_URL}/api/chat",
        json={"conversation_id": cid2, "message": "What is the secret access code?", "document_ids": [doc_id]},
        stream=True
    )
    assert res2.status_code == 200
    tokens = []
    done_payload = None
    for line in res2.iter_lines():
        if line:
            l = line.decode("utf-8")
            if l.startswith("data: ") and "token" in prev_line:
                tokens.append(l[6:])
            elif l.startswith("data: ") and "done" in prev_line:
                done_payload = l[6:]
            prev_line = l
        else:
            prev_line = ""

    full_answer = "".join([t.strip('"') for t in tokens])
    print(f"Model Answer: {full_answer}")
    print(f"Done event payload: {done_payload}")
    assert "DELTA-99" in full_answer, f"Expected DELTA-99 in answer, got: {full_answer}"
    assert "usage" in done_payload, f"Expected usage in done payload: {done_payload}"

    # 3. Empty message with document attached -> defaults to "Describe this file."
    print("\n--- Test 3.3: Empty message with document attached ---")
    res3 = requests.post(
        f"{BASE_URL}/api/chat",
        json={"conversation_id": cid2, "message": "", "document_ids": [doc_id]},
        stream=True
    )
    assert res3.status_code == 200
    tokens3 = []
    for line in res3.iter_lines():
        if line:
            l = line.decode("utf-8")
            if l.startswith("data: ") and "token" in prev_line:
                tokens3.append(l[6:])
            prev_line = l
        else:
            prev_line = ""
    reply3 = "".join([t.strip('"') for t in tokens3])
    print(f"Default prompt reply: {reply3[:120]}...")
    assert len(reply3) > 10

    # 4. Empty message with NO documents -> rejected with 400
    print("\n--- Test 3.4: Empty message with NO documents ---")
    res4 = requests.post(
        f"{BASE_URL}/api/chat",
        json={"conversation_id": cid1, "message": "", "document_ids": []}
    )
    print(f"Response status: {res4.status_code}, body: {res4.text}")
    assert res4.status_code == 422 or res4.status_code == 400

    # 5. RAG document selected -> clear warning stream
    print("\n--- Test 3.5: RAG mode document warning ---")
    w = PdfWriter()
    for _ in range(45):
        w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)

    rag_up = requests.post(
        f"{BASE_URL}/api/conversations/{cid2}/documents",
        files=[("files", ("large_manual.pdf", buf.getvalue(), "application/pdf"))]
    ).json()[0]
    rag_doc_id = rag_up["id"]

    for _ in range(10):
        time.sleep(0.5)
        d_rag = requests.get(f"{BASE_URL}/api/documents/{rag_doc_id}").json()
        if d_rag["status"] == "ready":
            break
    print(f"Large manual status: {d_rag['status']}, mode: {d_rag['mode']}")
    assert d_rag["mode"] == "rag"

    res5 = requests.post(
        f"{BASE_URL}/api/chat",
        json={"conversation_id": cid2, "message": "Summarize page 1", "document_ids": [rag_doc_id]},
        stream=True
    )
    assert res5.status_code == 200
    tokens5 = []
    for line in res5.iter_lines():
        if line:
            l = line.decode("utf-8")
            if l.startswith("data: ") and "token" in prev_line:
                tokens5.append(l[6:])
            prev_line = l
        else:
            prev_line = ""
    rag_msg = "".join([t.strip('"') for t in tokens5])
    print(f"RAG warning received: '{rag_msg}'")
    assert "too large for direct mode" in rag_msg

    print("\n" + "=" * 60)
    print("ALL MILESTONE 3 TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
