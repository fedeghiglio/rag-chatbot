# Session notes

## 2026-06-13 — Embeddings + Supabase vector store

### What we built
- **`embeddings_explorer.py`** — Voyage AI (`voyage-3`, 1024-dim) similarity playground.
  - `embed_text`, `cosine_similarity` (pure Python, no numpy), `compare`.
  - `__main__` batches all texts into one embed call and ranks 5 sentence pairs.
- **`db.py`** — the store→retrieve core of the RAG pipeline.
  - `embed_and_store(text, source, chunk_index) -> str` — embeds with `voyage-3` and inserts into the `documents` table; returns the new row id.
  - `search_similar(query, top_k=5) -> list[dict]` — embeds the query and ranks via the `match_documents` pgvector RPC; returns `id, content, source, chunk_index, similarity`.
  - `delete_test_rows()` — clears rows where `source = 'test'`; called at the top of `__main__` so the demo is idempotent (the 3 sample rows are tagged `source='test'`).
  - Keys from env: `VOYAGE_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`. Uses supabase-py only (no raw SQL from Python).
- **`schema.sql`** — `match_documents(query_embedding vector(1024), match_count int, match_threshold float)`, cosine similarity via pgvector `<=>`. Run in the Supabase SQL editor.
- Added `supabase` dependency (`uv add supabase`).
- **`chunker.py`** — turns a PDF into embed-ready chunks.
  - `chunk_pdf(pdf_path) -> list[dict]` — extracts text with `pypdf`, splits into **512-token** windows with **50-token overlap** (token boundaries via tiktoken `cl100k_base`), skips chunks < 50 tokens. Each dict: `text, source (filename only), chunk_index (0-based), token_count`.
  - `__main__` takes the PDF path as `sys.argv[1]` and prints total/avg/min/max chunk size + first/last 200-char previews.
  - Added deps `pypdf tiktoken`.
  - Verified on a generated 14-chunk PDF: indices contiguous, interior chunks all 512 tokens, 13/13 adjacent pairs share an exact 50-token overlap.
  - Hardened: validates the `%PDF-` magic header and wraps `PdfReader` so a non-PDF (e.g. an HTML error page saved as `.pdf`) or corrupt file gives a clean `error: ...` + exit 1 instead of a pypdf traceback.
- **`ingestor.py`** — wires chunker + db into a PDF→vector-store pipeline.
  - `ingest_pdf(pdf_path) -> dict` — `chunk_pdf()` → `embed_and_store()` per chunk; returns `{source, total_chunks, stored_ids (list[int]), failed_chunks (list[int])}`.
  - Paces embeds in batches of 3 with a 20s pause (Voyage 3 RPM); prints `Ingesting chunk X/total...`.
  - Per-chunk errors are caught, logged, added to `failed_chunks`, and the run continues — one bad chunk never crashes the ingest.
  - `__main__` takes a PDF path, prints the summary, then runs a test query `"what is constitutional AI?"` via `search_similar` (top 3).
  - Logic verified with mocked deps (failure path, id collection, batch pauses, empty PDF). Progress prints use `flush=True` so they stream live even when stdout is redirected to a file.
  - **Real ingest done:** `test.pdf` → **61/61 chunks stored, 0 failures** (~20 min on the 3 RPM free tier).
- **`rag.py`** — the generation layer (retrieve → ground → answer with citations).
  - `answer(question, top_k=5) -> dict` → `{answer, sources, question, chunks_used}`. Calls `search_similar`, injects chunks into a grounded system prompt, asks Claude to answer using ONLY that context and cite sources (or refuse if absent).
  - Model: **`claude-haiku-4-5-20251001`**, `max_tokens=1024`, via the Anthropic SDK (`ANTHROPIC_API_KEY` from env). Added `anthropic` dep.
  - Empty-retrieval guard returns a canned "not enough information" answer without calling Claude.
  - `__main__` runs 3 CAI questions. Verified: all 3 answered correctly and grounded in `test.pdf` chunks; the RLHF question did **not** trigger the refusal path because the paper genuinely covers RLHF.
- **`main.py`** — FastAPI app over the pipeline (`uv run uvicorn main:app`, or `uv run python main.py`).
  - `POST /ingest` — multipart PDF upload → temp file saved under the **original filename** (so `source` is the real name, not the temp path) → `ingest_pdf()` → summary dict; non-PDF/unreadable → 400.
  - `POST /chat` — JSON `{question, top_k=5}` → `answer()` → full answer dict.
  - `GET /health` — `{status, model, db}`; pings Supabase with a `limit(1)` query (returns 503 if unreachable).
  - Routes are sync `def` so FastAPI offloads the blocking embed/Claude/ingest work to a threadpool. Added deps `fastapi uvicorn python-multipart`.
  - Verified via `TestClient`: /health → `ok / claude-haiku-4-5-20251001 / connected`; /ingest stored a 3-chunk test PDF (cleaned up after) and rejected a non-PDF with 400; /chat returned a grounded answer (`chunks_used=3`).
- **`ui.py`** — Streamlit front-end (`uv run streamlit run ui.py`); talks to the FastAPI server with `requests` only.
  - Sidebar: health badge (green Connected / red Disconnected, re-checked each run via `/health`), API base-URL input, PDF uploader + **Ingest PDF** button (spinner; success summary or red error), and a **Clear chat history** button.
  - Main: `Document Q&A` chat with `st.session_state`-persisted history; each assistant turn has a "Sources (N chunks used)" expander (source/chunk_index/similarity). Empty state prompts to upload; the Ask button is disabled + a warning shown when the API is unreachable.
  - Verified headlessly with Streamlit `AppTest` against the live server: connects, an Ask click returns a grounded answer with 5 sources, Clear empties the history. Added `streamlit` dep.

### Verified end to end
Stored 3 sentences; query `"what do dogs eat?"` → animals **0.730**, science 0.215, finance 0.149. Correct ranking.

### Gotchas learned
- **Voyage free tier = 3 requests/min.** Both scripts use retry/backoff (25s waits). Adding a payment method lifts the limit (free token allowance still applies).
- **The originally-deployed `match_documents` was broken** — only matched near-identical vectors and capped at 1 row, so real queries returned 0. `schema.sql` is the corrected version; redeploy it if the function is ever reset.
- **`documents` schema:** `id bigint PK, content text, embedding vector(1024), source text, chunk_index int, created_at timestamptz`.
- pgvector embeddings are inserted as the JSON-array string form (`json.dumps(vector)`).
- Secrets live in `~/.bashrc` (sourced into the shell before running).
- **Citation drift in `rag.py`:** Claude's inline `[Source: …, chunk N]` citations occasionally name a chunk that wasn't actually in the retrieved set — the answer stays grounded, only the prose citation drifts. The returned `sources` list (the real retrieved chunks) is authoritative. Future fix: Anthropic's native **citations API** returns verifiable cited spans instead of prose-formatted citations.

### What's next
- [x] **Chunking** — `chunker.py` (512-token chunks, 50 overlap). Done.
- [x] **Ingestion wiring** — `ingestor.py` (`ingest_pdf`): chunks → `embed_and_store`, batched for the 3 RPM limit, graceful per-chunk failures. Done.
- [x] **Real ingest** — `test.pdf` → 61/61 chunks stored, 0 failures (~20 min, 3 RPM free tier). Cleaned out 3 stale `source='test'` demo rows afterward; table now holds 61 `test.pdf` rows. Query `"what is constitutional AI?"` top 3 similarities: **0.572 / 0.571 / 0.547** — all on-topic Constitutional AI passages. Done.
- [x] **RAG generation** — `rag.py` (`answer`): retrieve → grounded Claude (`claude-haiku-4-5-20251001`) → cited answer, with a refusal path. Done.
- [x] **FastAPI layer** — `main.py`: `POST /ingest`, `POST /chat`, `GET /health`. Verified via `TestClient`. Done.
- [ ] **Async refactor** — CLAUDE.md mandates async-first (`asyncio` + `httpx`). Move to `voyageai.AsyncClient` and the async Supabase client; current `db.py` is sync.
- [ ] **Verifiable citations** — replace `rag.py`'s prose citations with Anthropic's citations API (see the citation-drift gotcha).
- [x] **Streamlit UI** — `ui.py` (sidebar: health badge, PDF ingest, clear-chat; main: chat with source expanders). Verified via `AppTest`. Done.
- [ ] **Scale** — add an HNSW/IVFFlat index on `documents.embedding` once row counts grow.
