"""FastAPI service exposing the RAG pipeline: ingest PDFs, chat over them, health.

Endpoints:
  POST /ingest  — multipart PDF upload -> ingest_pdf() -> summary dict
  POST /chat    — {question, top_k} -> answer() -> answer dict
  GET  /health  — liveness + Supabase reachability

Run: `uv run uvicorn main:app --reload` (or `uv run python main.py`).
"""

import os
import shutil
import tempfile

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client

# Importing these validates the env (db.py/rag.py raise on missing keys at import)
# and wires in the pipeline functions.
from .ingestor import ingest_pdf
from .rag import MODEL, answer

# Dedicated Supabase client for the health check, built from the same env vars the
# rest of the pipeline uses. Kept separate so /health doesn't reach into db.py
# internals.
_health_sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

app = FastAPI(title="RAG chatbot", version="0.1.0")


class ChatRequest(BaseModel):
    """Body for POST /chat. top_k defaults to 5 to match rag.answer()."""

    question: str
    top_k: int = 5


@app.post("/ingest")
def ingest(file: UploadFile = File(...)) -> dict:
    """Ingest an uploaded PDF into the vector store and return the ingest summary.

    Declared as a plain `def` (not `async def`) so FastAPI runs it in a threadpool:
    ingest_pdf() blocks on embedding + rate-limit pauses and would otherwise stall
    the async event loop for the whole run.
    """
    # basename() strips any directory components in the client-supplied filename
    # (path-traversal guard) and is the name we want recorded as `source`.
    filename = os.path.basename(file.filename or "upload.pdf")
    # Write the upload into a temp dir under its ORIGINAL name so chunk_pdf records
    # the real filename as `source` (chunk_pdf takes basename of the path it's given).
    tmpdir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmpdir, filename)
    try:
        # file.file is the underlying sync file object — fine to stream in a sync route.
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        summary = ingest_pdf(tmp_path)
    except (ValueError, FileNotFoundError) as exc:
        # Non-PDF / unreadable upload is a client error (400), not a server fault.
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        # Always clean up the temp copy, even if ingest raised.
        shutil.rmtree(tmpdir, ignore_errors=True)
    return summary


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Answer a question over the ingested documents (retrieve + grounded generation).

    Sync `def` for the same threadpool reason as /ingest — answer() blocks on the
    Voyage embed and the Claude call.
    """
    return answer(req.question, top_k=req.top_k)


@app.get("/health")
def health():
    """Liveness probe that also confirms Supabase is reachable."""
    try:
        # Cheapest round-trip that proves the DB connection works.
        _health_sb.table("documents").select("id").limit(1).execute()
        return {"status": "ok", "model": MODEL, "db": "connected"}
    except Exception as exc:
        # Return 503 so orchestrators/uptime checks see an unhealthy status, while
        # keeping the same response shape for clients.
        return JSONResponse(
            status_code=503,
            content={"status": "error", "model": MODEL, "db": f"disconnected: {exc}"},
        )


if __name__ == "__main__":
    import uvicorn

    # Bind to localhost by default; override with HOST/PORT env vars if needed.
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
