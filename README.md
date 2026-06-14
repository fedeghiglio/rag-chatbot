# rag-chatbot

A production-minded **retrieval-augmented generation (RAG) chatbot over PDFs**. You upload a PDF; it is chunked into overlapping token windows, embedded with **Voyage AI** (`voyage-3`, 1024-dim), and stored in **Supabase** (Postgres + pgvector). At query time the question is embedded, the most similar chunks are retrieved via a pgvector cosine search, and **Claude** (`claude-haiku-4-5`) answers using only that retrieved context — with source citations and a refusal path when the answer isn't in the documents. A **FastAPI** backend exposes the pipeline and a **Streamlit** frontend provides the chat UI.

## Project structure

```
rag-chatbot/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI app (POST /ingest, POST /chat, GET /health)
│   │   ├── rag.py           # generation layer (retrieve -> grounded Claude)
│   │   ├── db.py            # storage + retrieval (Supabase pgvector)
│   │   ├── chunker.py       # PDF -> token chunks
│   │   └── ingestor.py      # ingestion pipeline (chunk -> embed -> store)
│   ├── Dockerfile           # backend image (build context = repo root)
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
│   ├── ui.py                # Streamlit app
│   └── Dockerfile.streamlit # frontend image (build context = repo root)
├── db/
│   └── schema.sql           # match_documents() pgvector function
├── scripts/
│   └── embeddings_explorer.py  # learning script, not shipped
├── .env.example
├── .gitignore
├── .dockerignore
├── railway.toml
└── README.md
```

The app modules form a Python package (`app`) and import each other with relative
imports (`from .db import …`), so run them as modules from `backend/`.

## Run locally

Prereqs: [uv](https://docs.astral.sh/uv/), a Supabase project with pgvector, and Voyage + Anthropic API keys. All `uv` commands run from `backend/` (that's where `pyproject.toml`/`uv.lock` live).

```bash
# 1. Install dependencies
cd backend && uv sync

# 2. One-time DB setup: run db/schema.sql in the Supabase SQL editor
#    (creates the match_documents() pgvector function).

# 3. Provide environment variables (the app reads them from the process env;
#    there is no .env auto-loading). From the repo root:
cp .env.example .env          # then edit .env with real values
set -a; source .env; set +a   # export every var into the current shell

# 4. Backend API on http://localhost:8000  (run from backend/)
cd backend && uv run uvicorn app.main:app --reload

# 5. Frontend on http://localhost:8501 (another shell, env exported).
#    Uses the backend venv; ui.py lives in ../frontend.
cd backend && uv run streamlit run ../frontend/ui.py
```

> Set `FASTAPI_URL` to point the UI at a non-default backend (otherwise it defaults to `http://localhost:8000`; also editable in the sidebar at runtime).

CLI alternatives (from `backend/`, run as modules so relative imports resolve):

```bash
uv run python -m app.ingestor ../test.pdf   # ingest a PDF
uv run python -m app.rag                     # run the sample queries
uv run python ../scripts/embeddings_explorer.py   # learning script
```

## Deploy to Railway

Two services from one repo, both built with the repo root as the Docker build context.

1. **Push to GitHub**, then create a Railway project from the repo.
2. **Backend service** — uses `railway.toml` (`dockerfilePath = "backend/Dockerfile"`). The Dockerfile CMD binds `$PORT` via a Python entrypoint. Set the four environment variables (below) in the service's Variables tab.
3. **Frontend service** — add a second service from the same repo, set its **Dockerfile path** to `frontend/Dockerfile.streamlit`, and set its **start command** to bind `$PORT`:
   ```
   streamlit run ui.py --server.port $PORT --server.address 0.0.0.0
   ```
   Set `FASTAPI_URL` (Variables tab) to the backend service's public URL so the UI defaults to it.
4. **Database** — run `db/schema.sql` in Supabase once (if not already done).

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key — Claude generation (`claude-haiku-4-5`) |
| `VOYAGE_API_KEY` | Voyage AI key — `voyage-3` embeddings |
| `SUPABASE_URL` | Supabase project URL (`https://<ref>.supabase.co`) |
| `SUPABASE_KEY` | Supabase **service-role** key — read/write to the `documents` table |
| `FASTAPI_URL` | (frontend only) Backend base URL the Streamlit UI defaults to |

See `.env.example` for the template. Never commit real keys — `.env` is gitignored.
