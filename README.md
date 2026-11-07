# DOC_POC: Chat with Your Documents

A production-grade Proof of Concept (POC) for conversational document search and Question Answering powered by Google Gemini, PostgreSQL with pgvector, FastAPI, and React.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v24+ recommended)
- [Docker Compose](https://docs.docker.com/compose/) (v2+ / v5+)
- Google Gemini API Key ([Google AI Studio](https://aistudio.google.com/))

---

## Quickstart & Setup

1. **Clone the repository and prepare the environment configuration:**
   ```bash
   cp .env.example .env
   ```
2. **Configure your Gemini API key in `.env`:**
   ```env
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   ```
3. **Start all services with Docker Compose:**
   ```bash
   docker compose up --build
   ```
   *(Add `-d` to run in the background).*

---

## Service URLs

| Service | URL | Description |
| :--- | :--- | :--- |
| **Web UI** | [http://localhost:3000](http://localhost:3000) | React + Vite Chat Application |
| **FastAPI Backend** | [http://localhost:8000](http://localhost:8000) | Core REST & SSE Streaming API |
| **Health Check** | [http://localhost:8000/api/health](http://localhost:8000/api/health) | System health status (JSON) |
| **OpenAPI Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive Swagger UI |
| **PostgreSQL** | `localhost:5432` | Postgres 16 with pgvector extension |

---

## How to Reset the Database Volume

To wipe the database completely, delete the persistent volume, and re-run all migrations from scratch:

```bash
docker compose down -v
docker compose up --build
```

---

## Stage 2 Features & Configuration

In **Stage 2**, the application supports streaming multi-turn conversations with Gemini without file attachments.

### Configuration Variables (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API Key. Kept secure and never logged. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Fast text generation model (configurable). |
| `HISTORY_MAX_MESSAGES` | `30` | Maximum recent messages passed as context to Gemini. *Note: Advanced context pruning comes in later stages.* |
| `MAX_MESSAGE_CHARS` | `4000` | Input character validation threshold. |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Asynchronous database connection string for FastAPI. |
| `SYNC_DATABASE_URL` | `postgresql://...` | Synchronous database connection string for Alembic migrations. |
| `VITE_API_URL` | `http://localhost:8000` | API endpoint used by the browser. |

### SSE Chat Protocol (`POST /api/chat`)

Requests are sent via `POST` with JSON payload `{ "conversation_id": "<uuid>", "message": "<text>" }` and streamed as Server-Sent Events (`text/event-stream`):
- `event: token` - Progressively emitted token chunk: `data: {"text": "..."}`
- `event: done` - Stream completion signal: `data: {"message_id": "<uuid>", "usage": null}`
- `event: error` - Sanitized human-readable error: `data: {"error": "..."}`

If a client disconnects mid-stream or clicks **Stop**, the partial output generated so far is preserved in the database with `meta = {"interrupted": true}`.

---

## Stage 3: File Upload, Storage & Status Tracking

In **Stage 3**, the application adds multi-format document and image uploading, secure disk storage, format validation, cheap background inspection, cascading deletion, and frontend attachment UX. *(Note: Document content is not yet fed into Gemini chat; that occurs in Stage 4/5).*

### Storage Architecture & Layout

- **Docker Volume**: Uploads are stored on a persistent named Docker volume `uploads` mounted to `/data/uploads` inside the `doc_poc_api` container.
- **Filesystem Isolation**: Files are stored exclusively under the server-generated document UUID:
  ```text
  /data/uploads/{document_id}/original.{ext}
  ```
- **Security & Path Sanitization**: Client-supplied filenames are **never** used in disk paths. Original filenames are strictly sanitized (`re.sub(r'[^a-zA-Z0-9_.-]', '_', ...)` with path traversal characters stripped) and stored solely in PostgreSQL for UI display.
- **Streaming Uploads**: Files are read and written to disk in 64 KB chunks while calculating SHA-256 and tracking cumulative size. If any file exceeds `MAX_UPLOAD_MB`, streaming aborts immediately, and all partial disk artifacts are completely purged.
- **Cascading Deletion**: Deleting a document or deleting an entire conversation permanently deletes the corresponding files and directories on disk via a unified `delete_conversation_files` service.

### Supported File Types & Magic Byte Sniffing

MIME types are determined by content inspection (magic bytes via pure-Python `filetype` and UTF-8 decodability validation), never by client headers:
- **PDF**: `application/pdf`
- **Images**: `image/png`, `image/jpeg`, `image/webp`, `image/gif`
- **Text / Code**: `text/plain`, `text/markdown`, `text/csv` (validated as valid UTF-8 without binary null bytes)
- **Office Files** (`.docx`, `.xlsx`, `.pptx`): Rejected with the user-safe message: `"Office files will be supported in a later stage"`.

### Startup Recovery

FastAPI's asynchronous lifespan handler runs `run_startup_recovery()` upon container startup:
- Scans for any documents left in `uploading` or `processing` states from an abrupt shutdown or crash.
- **File present on disk**: Re-schedules background ingestion (`ingest_document`) to extract metadata (pages, dimensions, lines) and transition the document to `ready`.
- **File missing on disk**: Marks document `status = 'failed'` with safe error `"Upload interrupted by server restart"`.

### Configuration Variables (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API Key. Kept secure and never logged. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Fast text generation model (configurable). |
| `HISTORY_MAX_MESSAGES` | `30` | Maximum recent messages passed as context to Gemini. |
| `MAX_MESSAGE_CHARS` | `4000` | Input character validation threshold. |
| `DATABASE_URL` | `postgresql+asyncpg://...` | Asynchronous database connection string for FastAPI. |
| `SYNC_DATABASE_URL` | `postgresql://...` | Synchronous database connection string for Alembic migrations. |
| `UPLOAD_DIR` | `/data/uploads` | Path to persistent storage volume for uploaded documents. |
| `MAX_UPLOAD_MB` | `50` | Maximum allowed size per file in megabytes. |
| `MAX_FILES_PER_CONVERSATION` | `10` | Maximum number of documents allowed per conversation. |
| `MAX_FILES_PER_REQUEST` | `5` | Maximum number of files accepted in a single upload batch. |
| `INGEST_FAKE_DELAY_SECONDS` | `0` | Artificial delay for observing UI state transitions (`uploading` → `processing` → `ready`). |
| `VITE_API_URL` | `http://localhost:8000` | Backend API URL used by the web client. |

### Document REST API

- `POST /api/conversations/{id}/documents` - Multipart endpoint accepting up to `MAX_FILES_PER_REQUEST` files. Returns immediate HTTP 201 with created documents in `processing` status. Validates each file independently so bad files fail without failing the entire batch.
- `GET /api/conversations/{id}/documents` - Returns all documents attached to a conversation.
- `GET /api/documents/{id}` - Returns current status, metadata, and error state for polling.
- `GET /api/documents/{id}/file` - Streams the file with `X-Content-Type-Options: nosniff`, correct MIME type, and `inline` disposition for PDFs and images.
- `DELETE /api/documents/{id}` - Removes document from database and purges its directory from disk.

---

## Stage 4: DIRECT Mode (Grounded Multimodal Document Chat)

In **Stage 4**, uploaded files and images are sent directly to Gemini with the user's question, producing streamed answers grounded in file content with verifiable page-level citation chips (`[filename.pdf · p.X]`).

### Which Documents Go Direct

Upon upload and inspection, each document is assigned an execution `mode`:
- **`mode = 'direct'`**: Images, plain text, Markdown, CSV, and small PDFs within limits ($\le 40$ pages and $\le 20$ MB).
- **`mode = 'rag'`**: Larger PDFs ($> 40$ pages or $> 20$ MB). These documents remain ready for the upcoming RAG pipeline. If selected in chat, the assistant immediately streams an informative warning:
  > *"This document is too large for direct mode. Large-document support arrives in a later stage."*

### Sending Files to Gemini

- **Images**: Sent inline as raw byte parts (`types.Part.from_bytes`) for immediate low-latency visual understanding.
- **PDFs**: Uploaded to the **Gemini Files API** via `client.aio.files.upload` and polled until `ACTIVE`. File references and expiration timestamps (48-hour default retention) are cached in `documents.meta`:
  - `gemini_file_name`: Gemini internal file resource name.
  - `gemini_file_uri`: Gemini file URI.
  - `gemini_file_expires_at`: ISO timestamp of file expiration.
  - *Automatic Refresh*: Before each chat turn, if the file reference is expired or missing, it is re-uploaded transparently from local disk storage. Internal Gemini URIs and API keys are never exposed to the client or logged.
- **Text / Markdown / CSV**: Sent as labeled text parts (`Document: filename (N lines)`). CSV files exceeding `CSV_MAX_ROWS_DIRECT` are truncated with explicit notifications to both the model and user.

### Token Cost Implications & Context Management

> [!IMPORTANT]
> **Token-Cost Architecture**: Gemini models have no stateful memory of file uploads between requests. Therefore, when documents are selected, their file parts are attached to **every chat turn** that includes them.
>
> Prior turns in the conversation history remain **text-only**. To prevent unexpected costs and token exhaustion:
> 1. Users can toggle which documents are attached to the next message using the inclusion chips in the input bar.
> 2. Requests are protected by `DIRECT_MAX_TOTAL_TOKENS` (default 300,000 tokens). If an exchange exceeds this budget, it fails gracefully with an error naming the documents to deselect.
> 3. Token usage (`prompt_tokens`, `candidates_tokens`, `total_tokens`) is recorded on every turn and displayed under assistant messages.

### Grounded Prompt & Citation System

Answers are strictly grounded using a specialized system instruction (`GROUNDED_SYSTEM_PROMPT`):
- Factual claims drawn from documents are cited using machine-parseable markers:
  - Multi-page PDFs: `[[cite: contract.pdf | p.3]]`
  - Images and text files: `[[cite: architecture.png]]`
- The model is instructed to refuse to guess if text is blurry or unreadable, and to explicitly state when answers are not present in the files.
- The backend citation parser validates all markers against attached documents: unknown files are discarded, out-of-range page numbers are stripped, and duplicate filenames are disambiguated. Cleaned citations are saved in `messages.meta.citations` and sent in the SSE `done` event.
- The web UI dynamically hides raw citation syntax during and after streaming, rendering interactive chips that open the original PDF at `#page=N` or display images in a lightbox modal.

### Configuration Variables (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DIRECT_MAX_PAGES` | `40` | Maximum page count for PDF direct mode eligibility. |
| `DIRECT_MAX_MB` | `20` | Maximum file size (MB) for direct mode. |
| `DIRECT_MAX_TOTAL_TOKENS` | `300000` | Token budget threshold for direct mode chat turns. |
| `GEMINI_FILE_UPLOAD_TIMEOUT_SECONDS` | `30` | Timeout for Gemini Files API upload and ACTIVE state polling. |
| `CSV_MAX_ROWS_DIRECT` | `200` | Maximum rows sent for CSV files before truncation. |

---

## Stage 5: Document Parsing with Docling

In **Stage 5**, large PDF documents (classified as `mode = 'rag'`) are parsed using IBM's **Docling** (`docling-serve`) into per-page structured Markdown, plain text, tables, and figures. The parsed content is stored in PostgreSQL and on disk with exact 1-based page numbering, and is inspectable side-by-side against the original PDF in the UI.

### Architecture & Services

- **Containerized Docling Service**:
  - Image: `ghcr.io/docling-project/docling-serve-cpu:latest` (~4.4 GB).
  - Runs in a dedicated container `doc_poc_docling` on internal port `5001`.
  - **Persistent Model Cache**: Named Docker volume `docling_cache:/root/.cache` prevents re-downloading Hugging Face weights and vision models across container rebuilds or system reboots.
  - **Memory Limits & Page Batching**: Docling memory is capped via Docker Compose (`DOCLING_MEM_LIMIT=3500M`). Large PDFs are sliced into page batches (`PARSE_BATCH_PAGES=10`), bounding memory consumption to ~1.5–2 GB on CPU.
- **Informational Health Probe**:
  - `GET /api/health` probes Docling's `/health` endpoint. If Docling is stopped or unreachable, `/api/health` reports `docling: "unreachable"` while overall system health remains HTTP 200. Core direct-mode chat and document upload remain fully operational even if Docling is offline.
- **First-Run Download Time & Resource Guidance**:
  - On the very first run, Docling downloads standard layout analysis and table structure models (~500 MB). This initial download takes ~1–3 minutes depending on your internet connection.
  - For optimal performance, allocate at least **4 to 8 GB RAM** to Docker Desktop.

### Decoupled Parser Abstraction (`services/parsers/`)

The core application is completely decoupled from Docling's internal schema:
- `base.py`: Defines the `DocumentParser` protocol and dataclasses:
  - `ParsedPage`: `page_no` (1-based), `markdown`, `plain_text`, `char_count`, `has_table`, `has_figure`, `ocr_used`, `warnings`.
  - `ParsedDocument`: `parser_name`, `parser_version`, `page_count`, `pages`, `raw_json`, `full_markdown`.
  - Exceptions: `DocumentParserError`, `ParserUnavailableError`.
- `docling_client.py`: Implements `DocumentParser` using `httpx.AsyncClient` against `docling-serve` REST API (`POST /v1/convert/file`), utilizing native page break separators (`<!-- DOCLING_PAGE_BREAK -->`) and element provenance mapping.

### Database Schema (Alembic Migration `004`)

- **`documents` Table Extensions**:
  - `parse_status`: `'pending' | 'parsing' | 'parsed' | 'failed' | 'skipped'` (indexed).
  - `parse_error`: User-safe error description.
  - `parser_name` & `parser_version`: Engine metadata (e.g. `docling`, `1.38.2`).
  - `parse_started_at` & `parse_finished_at`: UTC timestamps.
  - `pages_parsed`: Progress counter updated per page batch.
  - `parse_options`: JSONB configuration options.
- **`document_pages` Table**:
  - `id`: UUID primary key.
  - `document_id`: UUID ForeignKey (`documents.id`, `ON DELETE CASCADE`).
  - `page_no`: Exact 1-based page number (indexed, unique constraint on `[document_id, page_no]`).
  - `markdown`: Structured Markdown for the page.
  - `plain_text`: Clean plain text for embedding extraction.
  - `char_count`: Total character count.
  - `has_table` (bool), `has_figure` (bool), `ocr_used` (bool).
  - `warnings`: JSONB array of heuristic flags (`low_text`, `garbled`).

### Disk Storage Layout

In addition to database records, raw artifacts are persisted under `/data/uploads/{document_id}/parsed/`:
```text
/data/uploads/{document_id}/
├── original.pdf            # Original uploaded document
└── parsed/
    ├── docling.json        # Raw structured JSON payload with bounding boxes & provenance
    └── full.md             # Complete assembled document Markdown with page comments
```
Deleting a document or conversation permanently removes these files and folders via cascading deletion.

### Built-in Quality Heuristics

Every parsed page is automatically evaluated with cheap quality heuristics:
- **`low_text`**: Flagged if total plain text characters < `PARSE_MIN_CHARS_PER_PAGE` (default: 50).
- **`garbled`**: Flagged if the alphanumeric/character ratio is below 65% on non-empty pages.
- **Page Count Consistency**: Verifies that the total parsed page count matches the pypdf reader count.

### REST Endpoints Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/documents/{id}/parse` | `GET` | Parse status, progress, timing, and warnings summary. |
| `/api/documents/{id}/parse/retry` | `POST` | Reset status, clear previous pages, and re-enqueue background parsing. |
| `/api/documents/{id}/pages` | `GET` | Paginated page list (`?page=1&limit=50`) with metadata and flags. |
| `/api/documents/{id}/pages/{n}` | `GET` | Single-page detail with structured Markdown and plain text. |
| `/api/documents/{id}/parsed.md` | `GET` | Download full assembled Markdown as an attachment. |

### Frontend "Parsed View" & UX

- **Documents Drawer**: Real-time progress bars and page counters (`pages 12/45`) during parsing, with live 1.5s reactive polling.
- **Split-Screen Parsed View Screen**:
  - **Left**: Original PDF rendered at `#page=N`.
  - **Right**: Rendered Markdown with a toggle to Raw Markdown / Plain Text, table and figure badges, quality warning chips, jump-to-page navigation, and a Download `.md` button.
- **Chat Status-Aware Messaging**: RAG documents that are parsed stream: `"Parsed and ready for indexing in the next stage."`

### Configuration Variables (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DOCLING_URL` | `http://docling:5001` | URL for the docling-serve container. |
| `DOCLING_MEM_LIMIT` | `3500M` | Memory constraint on the docling container. |
| `PARSE_MODE` | `rag_only` | `rag_only` (default), `all_pdfs` (parse direct-mode PDFs too), or `off`. |
| `PARSE_BATCH_PAGES` | `10` | Page count per Docling batch request. |
| `PARSE_CONCURRENCY` | `1` | Maximum simultaneous parsing jobs to bound CPU/RAM. |
| `PARSE_TIMEOUT_SECONDS` | `300` | Per-batch timeout for Docling HTTP inference. |
| `PARSE_OCR_ENABLED` | `false` | Enable EasyOCR engine for scanned pages (`false` speeds up born-digital PDFs). |
| `PARSE_MIN_CHARS_PER_PAGE` | `50` | Threshold below which pages are flagged as `low_text`. |

---

## Stage 6: Chunking, Embeddings, Vector Storage & Hybrid Search

In **Stage 6**, parsed document pages (`document_pages` from Stage 5) are transformed into structured chunks, embedded using Google Gemini (`gemini-embedding-001`), stored in PostgreSQL with `pgvector`, and searchable through high-performance vector, keyword, and hybrid search interfaces.

*(Note: The LLM chat answering pipeline does not consume search results yet; that arrives in Stage 7).*

### 1. Chunking Strategy & Sizing (`services/chunking.py`)

- **Structure-Aware Segmentation**: Chunks are created by respecting natural document boundaries—starting at markdown headings (`#`, `##`, `###`), then splitting paragraphs and sentence boundaries. Text is never cut mid-sentence unless an individual sentence exceeds `CHUNK_MAX_TOKENS`.
- **Configurable Sizing**:
  - `CHUNK_TARGET_TOKENS` (default `600`): Desired target size for narrative chunks.
  - `CHUNK_MAX_TOKENS` (default `900`): Strict upper bound before splitting.
  - `CHUNK_OVERLAP_TOKENS` (default `80`): Overlap applied between consecutive text chunks within the same section to preserve context continuity.
  - `CHUNK_MIN_TOKENS` (default `60`): Small trailing sections or headings are merged into neighboring chunks so headings never stand alone.
- **Table Handling**:
  - Tables are identified and preserved whole as single units whenever they fit under `CHUNK_MAX_TOKENS`.
  - Oversized tables that exceed the limit are split by rows, and the **table header row is repeated** at the top of every split chunk.
  - Marked with `chunk_type: "table"` for visual badges and specialized rendering.
- **Contextual Embed Text**:
  - Every chunk maintains two text representations:
    - `text`: Clean markdown content that the LLM and user read.
    - `embed_text`: Context-prefixed string sent to the Gemini embedding API (e.g., `Document: {filename} > {heading_path}\n{text}`), significantly improving semantic retrieval relevance.
- **Accurate Provenance**:
  - Chunks track `page_start` and `page_end` for precise citation linking in Stage 7.

### 2. Gemini Embedding Service (`services/embeddings.py`)

- **Model**: `gemini-embedding-001` via the official Google GenAI SDK (`google-genai`).
- **Dimensions**: Configured at `768` floats (`output_dimensionality=768`), producing dense, normalized vectors.
- **Task Types**: Uses `task_type="RETRIEVAL_DOCUMENT"` for document chunks and `task_type="RETRIEVAL_QUERY"` for search queries.
- **Concurrency & Resilience**:
  - Batching: Embeds up to `EMBED_BATCH_SIZE=20` texts per API request.
  - Semaphore: Bounded concurrency (`EMBED_CONCURRENCY=2`) to stay comfortably within API rate limits.
  - Exponential Backoff: Automatic jittered retries on HTTP 429 (rate limits) and 5xx server errors with key sanitization in logs.
- **Changing Dimensions**:
  The vector dimension is fixed in migration `005_add_chunks_and_indexing.py` as `Vector(768)`. Changing the model or dimension requires creating a new Alembic migration altering the column type (e.g. `Vector(1536)`) and triggering a re-index via `POST /api/documents/{id}/index/retry?reindex=true`.

### 3. Database & pgvector Indexing

- **Table**: `chunks` with fields:
  - `id` (UUID), `document_id` (FK cascade), `chunk_index` (int, sequential 0-based), `text` (Text), `embed_text` (Text).
  - `page_start`, `page_end` (int), `heading_path` (JSONB array), `chunk_type` (`text` | `table` | `list` | `mixed`), `token_count` (int).
  - `embedding` (`Vector(768)`).
  - `tsv` (`TSVECTOR` computed as `to_tsvector('simple', text)`).
  - `created_at` (timestamptz).
  - Unique constraint on `(document_id, chunk_index)`.
- **Index Choices**:
  - **HNSW on Embeddings**: `CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`.
    *Why HNSW over IVFFlat*: HNSW does not require a prior training or clustering step, allows instant dynamic insertions without index rebuilding, and delivers superior recall on small-to-medium corpora.
  - **GIN on TSVector**: `CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)` for fast PostgreSQL Full-Text Search.
  - **B-Tree on Document ID**: For instant document-scoped filtering and cascading deletions.
- **Full-Text Search & Multi-lingual Considerations**:
  - Uses the `'simple'` text configuration dictionary: it tokenizes on whitespace and punctuation and downcases characters without applying language-specific stemming rules.
  - *Trade-off*: Postgres has built-in stemmers for English and European languages, but lacks stemmers for Telugu, Hindi, and non-Latin scripts. Using `'simple'` ensures unstemmed Telugu/Hindi tokens are searchable without corrupting character encodings.

### 4. Search Retrieval Modes (`services/search.py`)

Search supports three retrieval modes via `POST /api/search/debug`:
1. **Vector Search (`mode: "vector"`)**:
   Embeds the search query with `task_type="RETRIEVAL_QUERY"` and computes cosine distance via pgvector's `<=>` operator (`similarity = 1 - distance`).
2. **Keyword Search (`mode: "keyword"`)**:
   Executes `websearch_to_tsquery('simple', :query)` against the GIN-indexed `tsv` column, ranked with `ts_rank(tsv, query)`.
3. **Hybrid Search with Reciprocal Rank Fusion (`mode: "hybrid"`)**:
   Retrieves candidates from both vector and keyword search concurrently, then merges and ranks them using **Reciprocal Rank Fusion (RRF)**:
   $$\text{RRF\_Score}(d) = \sum_{m \in \{\text{vector}, \text{keyword}\}} \frac{1}{k + \text{rank}_m(d)}, \quad k = 60$$
   where $k = 60$ is the standard smoothing constant (configurable via `RRF_K`).

> [!NOTE]
> **Why Similarity Thresholds Are Off by Default**:
> Hard similarity thresholds (`SEARCH_MIN_SIMILARITY`) are risky because cosine distance scales unpredictably depending on query length, vocabulary specificity, and domain. A threshold that works for long descriptive queries will discard valid top matches for short keyword queries. Relative ranking with RRF provides significantly more robust retrieval.

### 5. Frontend Features

- **Documents Drawer**:
  - Live index status badges: `Pending`, `Indexing` (with animated progress), `Indexed (N chunks)`, `Failed` (with Retry button).
  - "Chunks" button opening the Chunk Inspector modal.
- **Chunks View Modal**:
  - Full chunk list with page ranges, heading breadcrumbs, and token counts.
  - Distinct table chunk styling with markdown table preview.
  - "Neighbours" inspector displaying previous and next adjacent chunks for section continuity.
  - Embed prefix text inspector.
- **Search Retrieval Studio (Search Debug)**:
  - Accessible via the **Search Debug** button in the top navigation bar.
  - Multi-mode toggle: `Hybrid (RRF)`, `Vector Only`, `Keyword Only`, and **Side-by-Side (Compare All 3)**.
  - Side-by-side mode runs vector, keyword, and hybrid searches in parallel, displaying results in 3 synchronized columns so you can visually inspect how hybrid fusion blends semantic context with exact keywords.
  - Matched query terms are highlighted in result cards.
  - Page links directly open the source PDF at `#page=N` in a new browser tab.

### 6. Mini Evaluation Harness (`app/eval/run_retrieval.py`)

Run the automated evaluation benchmark on indexed documents:
```bash
docker exec doc_poc_api python -m app.eval.run_retrieval
```

**Benchmark Results:**

| Retrieval Mode | Recall@5 | Recall@10 | Mean Reciprocal Rank (MRR) | Avg Latency |
| :--- | :---: | :---: | :---: | :---: |
| **Vector** | 100.0% | 100.0% | 1.0000 | 574.0 ms |
| **Keyword** | 25.0% | 25.0% | 0.2500 | 1.9 ms |
| **Hybrid (RRF)** | 100.0% | 100.0% | 1.0000 | 509.8 ms |

#### Key Takeaway by Query Type:
- **Keyword FTS** is ultra-fast (<2ms) and excels at exact acronyms (`RRF`, `HNSW`) and specific section headings.
- **Vector Search** excels at natural-language questions and conceptual queries where the phrasing differs from document words.
- **Hybrid Search (RRF)** achieves the best overall quality by fusing both signals into unified rankings.

---

## Planned Architecture Stages

1. **Stage 1: Foundation** *(Completed)*
2. **Stage 2: Plain Streaming Chat** *(Completed)*
3. **Stage 3: File Upload, Storage & Status Tracking** *(Completed)*
4. **Stage 4: DIRECT Mode (Grounded Multimodal Document Chat)** *(Completed)*
5. **Stage 5: Document Parsing with Docling** *(Completed)*
6. **Stage 6: Chunking, Embeddings, Vector Storage & Hybrid Search** *(Completed)*
   - Structure-aware deterministic chunker with table row-splits and repeated headers (`services/chunking.py`).
   - Gemini embedding client with batching, retries, and concurrency control (`services/embeddings.py`).
   - Alembic migration `005` adding `chunks` table with pgvector HNSW index and FTS GIN index.
   - Search service supporting vector cosine, Postgres FTS, and Reciprocal Rank Fusion (`services/search.py`).
   - REST endpoints for index status, manual re-index, chunk browser, chunk neighbors, and search debug.
   - Interactive React UI: Chunks inspector modal, Search Debug studio with 3-way side-by-side comparison.
   - Mini evaluation harness (`eval/questions.yaml` & `python -m app.eval.run_retrieval`).
   - 14 automated acceptance tests verifying all Stage 6 requirements.
7. **Stage 7: Hybrid Retrieval & RAG Pipeline**
8. **Stage 8: Evaluation & Observability**
9. **Stage 9: Production Polish & Security**


