# Project: rag-chatbot

## Goal
Build a production RAG chatbot over PDFs. Learning project that will become a portfolio piece and client deliverable.

## Stack
- Python 3.11+
- Package manager: uv (not pip)
- HTTP client: httpx (async)
- Data validation: pydantic v2
- LLM generation: Anthropic SDK (Claude Haiku 4.5, pinned to `claude-haiku-4-5-20251001`)
- Embeddings: Voyage AI (voyage-3, 1024 dims)
- Database: Supabase (postgres + pgvector)
- API layer: FastAPI
- UI: Streamlit (operator/admin), embeddable JS widget (client-facing)

## Layout
```
backend/
  app/
    main.py       # FastAPI app — /ingest, /chat, /health, /documents, /widget.js, /demo
    rag.py        # RAG pipeline — retrieval + Anthropic citations API
    db.py         # Supabase search + embed (Voyage AI)
    chunker.py    # PDF → token chunks (tiktoken, 512 tokens, 50 overlap)
    ingestor.py   # chunk + embed + store pipeline
    static/
      widget.js   # self-contained embeddable chat widget (Shadow DOM)
frontend/
  ui.py           # Streamlit UI (PDF upload + chat)
demo.html         # demo page embedding the widget (served at /demo)
db/
  schema.sql      # pgvector setup + match_documents RPC
```

## Commands
- Install dep: `uv add [package]`
- Run backend: `uv run uvicorn app.main:app --reload` (from `backend/`)
- Run Streamlit: `uv run streamlit run ../frontend/ui.py` (from `backend/`)
- Lint: `uv tool run ruff check .`

## Running locally
Two terminals from `backend/`:
1. `uv run uvicorn app.main:app --reload` → API at http://localhost:8000
2. `uv run streamlit run ../frontend/ui.py` → Streamlit at http://localhost:8501

Frontends:
- Streamlit (upload + chat): http://localhost:8501
- Widget demo: http://localhost:8000/demo

## API endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingest` | Upload PDF → chunk → embed → store |
| POST | `/chat` | `{question, top_k}` → grounded answer with citations |
| GET | `/documents` | Distinct ingested sources + chunk counts, most-recent first |
| GET | `/health` | Liveness + Supabase connectivity |
| GET | `/widget.js` | Serve embeddable widget script |
| GET | `/demo` | Serve demo HTML page |

## CORS
Configured via `ALLOWED_ORIGINS` env var (default `"*"` for demo).
For production set to comma-separated origins: `https://client.com,https://www.client.com`.
`allow_credentials` is always `False` (required when origins is `*`).

## Citations (Upgrade 1)
`rag.py` uses Anthropic's native citations API — no prompt-based citation injection.
- Each retrieved chunk is passed as a `document` content block (`source.type: "content"`) with `citations: {enabled: true}`.
- Response text blocks carry a `.citations` list; each citation has `cited_text` and `document_index` (maps back to the retrieved chunks array).
- `chunks_used` = distinct document indices actually cited (not just retrieved).
- No beta header needed — citations API is GA.
- Incompatible with `output_config.format`.

## Widget (Upgrade 2)
`backend/app/static/widget.js` — vanilla JS, zero build step, no framework.
- Embedded with: `<script src="https://<backend>/widget.js" data-api="https://<backend>"></script>`
- Uses Shadow DOM (`attachShadow`) for full bidirectional style isolation.
- All dynamic content uses `textContent` / `createTextNode` — never `innerHTML` (XSS safety).
- Shows cited passages in a collapsible `<details>` block under each answer.

## Rules
- Async-first: use asyncio and httpx
- Never hardcode API keys — os.environ only
- Type hints on all functions
- Comment every non-obvious line
- No LangChain — raw SDK and SQL only for now
