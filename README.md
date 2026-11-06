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

## Planned Architecture Stages

1. **Stage 1: Foundation** *(Completed)*
   - Docker Compose setup for PostgreSQL (`pgvector/pgvector:pg16`), FastAPI, and Web placeholder.
   - Automatic Alembic migration for `vector` extension.
   - Comprehensive `/api/health` monitoring endpoint.
2. **Stage 2: Plain Streaming Chat** *(Completed)*
   - Streaming text chat with Google Gemini (`google-genai` SDK).
   - Conversation and message persistence in PostgreSQL.
   - Sidebar conversation management (create, list, select, delete) and markdown message rendering.
   - Abortable stream generation with interrupted state persistence.
3. **Stage 3: File Upload, Storage & Status Tracking** *(Completed)*
   - Named Docker volume storage (`uploads:/data/uploads`) with UUID folder structure.
   - Content-sniffing file validation (PDF, images, text, Markdown, CSV; rejected Office docs).
   - Background ingestion with page counting (`pypdf`), dimension extraction (`Pillow`), and line counts.
   - Automatic container reboot recovery for interrupted uploads.
   - Frontend UX: drag-and-drop, paperclip picker, clipboard paste, real-time progress chips, and documents drawer.
4. **Stage 4: DIRECT Mode (Grounded Multimodal Document Chat)** *(Completed)*
   - Direct multimodal QA with Gemini vision and PDF understanding.
   - Gemini Files API caching, polling, and transparent auto-reupload on expiration.
   - Grounded prompt with machine-parseable citation markers (`[[cite: file \| p.X]]`).
   - Pure-function citation parser with validation, out-of-bounds page dropping, and duplicate disambiguation.
   - Interactive UI citation chips with PDF `#page=N` deep-linking and image lightbox modal.
   - Document attachment selection toggles, "Direct"/"RAG" mode badges, and per-message token usage.
5. **Stage 5: Document Parsing with Docling** *(Completed)*
   - Containerized Docling service (`docling-serve-cpu`) with persistent model cache volume (`docling_cache`).
   - Replaceable `DocumentParser` interface with memory-bounded page batching and progress callbacks.
   - Alembic migration `004` adding parsing fields and `document_pages` table with exact 1-based page indices.
   - Disk artifact storage (`parsed/docling.json` & `parsed/full.md`) with cascading cleanup.
   - Quality heuristics (`low_text`, `garbled`, page count mismatch validation).
   - REST API endpoints for parse status, retry, paginated pages, page detail, and markdown downloads.
   - Interactive split-screen "Parsed view" modal comparing original PDF page against parsed Markdown.
   - Concurrency limits, startup crash recovery, and resilience when Docling is offline.
6. **Stage 6: Chunking, Embeddings & Vector Storage**
7. **Stage 7: Hybrid Retrieval & RAG Pipeline**
8. **Stage 8: Evaluation & Observability**
9. **Stage 9: Production Polish & Security**

