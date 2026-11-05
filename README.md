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
3. **Stage 3: Document Ingestion & Parsing**
4. **Stage 4: Embeddings & Vector Storage**
5. **Stage 5: Hybrid Retrieval & RAG Pipeline**
6. **Stage 6: Grounded Generation & Citations**
7. **Stage 7: Evaluation & Observability**
8. **Stage 8: Production Polish & Security**
