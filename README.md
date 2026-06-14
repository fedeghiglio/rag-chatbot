# rag-chatbot

A production-minded **retrieval-augmented generation (RAG) chatbot over PDFs**. You upload a PDF; it is chunked into overlapping token windows, embedded with **Voyage AI** (`voyage-3`, 1024-dim), and stored in **Supabase** (Postgres + pgvector). At query time the question is embedded, the most similar chunks are retrieved via a pgvector cosine search, and **Claude** (`claude-haiku-4-5`) answers using only that retrieved context — with source citations and a refusal path when the answer isn't in the documents. A **FastAPI** service exposes the pipeline and a **Streamlit** app provides the chat UI.

## Architecture

```
Streamlit UI (ui.py) ──HTTP──▶ FastAPI (main.py)
                                  ├─ /ingest → chunker.py → Voyage embed → Supabase (db.py)
                                  ├─ /chat   → retrieve (pgvector) → Claude (rag.py)
                                  └─ /health → Supabase ping
```

| File | Role |
|------|------|
| `chunker.py` | PDF → 512-token chunks (50-token overlap) |
| `db.py` | `embed_and_store` / `search_similar` over Supabase pgvector |
| `ingestor.py` | Ingestion pipeline (chunk → embed → store) |
| `rag.py` | Retrieval + grounded Claude generation with citations |
| `main.py` | FastAPI: `POST /ingest`, `POST /chat`, `GET /health` |
| `ui.py` | Streamlit front-end |
| `schema.sql` | `match_documents` pgvector cosine-search function |

## Run locally

Prereqs: [uv](https://docs.astral.sh/uv/), a Supabase project with pgvector, and Voyage + Anthropic API keys.

```bash
# 1. Install dependencies
uv sync

# 2. One-time DB setup: run schema.sql in the Supabase SQL editor
#    (creates the match_documents() pgvector function).

# 3. Provide environment variables. The app reads them straight from the
#    process environment (no .env auto-loading), so export them into your shell:
cp .env.example .env        # then edit .env with real values
set -a; source .env; set +a # export every var into the current shell

# 4. Start the backend (http://localhost:8000)
uv run uvicorn main:app --reload

# 5. In another shell (same env vars exported), start the UI (http://localhost:8501)
uv run streamlit run ui.py
```

Then open the Streamlit app, upload a PDF in the sidebar, and ask questions. CLI alternatives: `uv run python ingestor.py <file.pdf>` to ingest, `uv run python rag.py` to query.

## Deploy to Railway

Two services from one repo — a FastAPI backend and a Streamlit frontend.

1. **Push to GitHub**, then create a Railway project from the repo.
2. **Backend service** — uses `Dockerfile` and `railway.toml` (start command binds Railway's `$PORT`). Set the four environment variables (below) in the service's Variables tab.
3. **Frontend service** — add a second service from the same repo, set its **Dockerfile path** to `Dockerfile.streamlit`, and set its **start command** to bind `$PORT`:
   ```
   streamlit run ui.py --server.port $PORT --server.address 0.0.0.0
   ```
   In the running Streamlit app, set the sidebar **API base URL** to the backend service's public Railway URL.
4. **Database** — run `schema.sql` in Supabase once (if not already done).

> **Python version:** the Dockerfiles use `python:3.14-slim` to match `pyproject.toml`'s `requires-python >=3.14`, so uv uses the image's own interpreter (no managed-Python download during the build).

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key — Claude generation (`claude-haiku-4-5`) |
| `VOYAGE_API_KEY` | Voyage AI key — `voyage-3` embeddings |
| `SUPABASE_URL` | Supabase project URL (`https://<ref>.supabase.co`) |
| `SUPABASE_KEY` | Supabase **service-role** key — read/write to the `documents` table |

See `.env.example` for the template. Never commit real keys — `.env` is gitignored.
