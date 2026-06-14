"""Ingest a PDF into the vector store: chunk it, embed each chunk, store the rows.

Ties together chunker.chunk_pdf (PDF -> token chunks) and db.embed_and_store
(chunk -> Voyage embedding -> Supabase row). Embedding is paced to stay within
Voyage's free-tier 3-requests/minute limit, and a single failing chunk never
aborts the run.
"""

import os
import sys
import time

from chunker import chunk_pdf
from db import embed_and_store, search_similar

# Pacing for Voyage's free tier (~3 requests/minute): embed BATCH_SIZE chunks,
# then pause BATCH_PAUSE seconds before the next batch. db.embed_and_store also
# retries individual 429s with backoff, so this pacing plus that retry keeps the
# run under the limit even if a window is briefly saturated.
BATCH_SIZE = 3
BATCH_PAUSE = 20


def ingest_pdf(pdf_path: str) -> dict:
    """Chunk, embed, and store a PDF; return a summary of what was ingested.

    Returns {source, total_chunks, stored_ids, failed_chunks}. Per-chunk failures
    are recorded in failed_chunks and do not stop the run.
    """
    chunks = chunk_pdf(pdf_path)
    total = len(chunks)
    # Use the filename the chunker recorded; fall back to the path basename when
    # the PDF produced no chunks (so the summary still names the source).
    source = chunks[0]["source"] if chunks else os.path.basename(pdf_path)

    stored_ids: list[int] = []
    failed_chunks: list[int] = []

    for i, chunk in enumerate(chunks):
        # 1-based for human-friendly progress output.
        # flush=True so progress streams live even when stdout is redirected to
        # a file/pipe (Python block-buffers stdout otherwise, hiding progress
        # until the process exits).
        print(f"Ingesting chunk {i + 1}/{total}...", flush=True)
        try:
            row_id = embed_and_store(
                chunk["text"], chunk["source"], chunk["chunk_index"]
            )
            # embed_and_store returns the bigint id as a str; normalize to int.
            stored_ids.append(int(row_id))
        except Exception as exc:
            # Catch broadly on purpose: the spec requires that one bad chunk
            # (embedding error, transient DB failure, etc.) never crashes the
            # whole ingest. Record its chunk_index and keep going.
            print(f"  chunk {chunk['chunk_index']} failed: {exc}", flush=True)
            failed_chunks.append(chunk["chunk_index"])

        # Pause after every full batch, but not after the final chunk (no point
        # sleeping when there's nothing left to embed).
        if (i + 1) % BATCH_SIZE == 0 and (i + 1) < total:
            print(f"  (rate-limit pause {BATCH_PAUSE}s)", flush=True)
            time.sleep(BATCH_PAUSE)

    return {
        "source": source,
        "total_chunks": total,
        "stored_ids": stored_ids,
        "failed_chunks": failed_chunks,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"usage: python {os.path.basename(sys.argv[0])} <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    # PDF-level failures (missing file, non-PDF, corrupt) surface as a clean
    # message here; per-chunk failures are handled inside ingest_pdf.
    try:
        summary = ingest_pdf(pdf_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        sys.exit(1)

    print("\n=== Ingest summary ===")
    print(f"source:       {summary['source']}")
    print(f"total_chunks: {summary['total_chunks']}")
    print(f"stored:       {len(summary['stored_ids'])}")
    print(f"failed:       {len(summary['failed_chunks'])}")
    if summary["failed_chunks"]:
        print(f"failed chunk indices: {summary['failed_chunks']}")

    # Smoke-test retrieval against what we just ingested.
    query = "what is constitutional AI?"
    print(f"\nQuery: {query!r}\nTop 3 results:")
    for r in search_similar(query, top_k=3):
        # similarity is cosine similarity (1.0 = identical meaning).
        print(f"  {r['similarity']:.3f} | [{r['source']}] {r['content'][:80]!r}")
