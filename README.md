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
4. **Stage 4: Embeddings & Vector Storage**
5. **Stage 5: Hybrid Retrieval & RAG Pipeline**
6. **Stage 6: Grounded Generation & Citations**
7. **Stage 7: Evaluation & Observability**
8. **Stage 8: Production Polish & Security**

