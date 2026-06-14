"""Store and retrieve document chunks in Supabase using pgvector + Voyage embeddings.

Embeddings come from Voyage AI (`voyage-3`, 1024 dimensions). Vector similarity
search runs server-side in Postgres via the `match_documents` pgvector function
(see schema.sql) and is invoked through the supabase-py RPC client — no raw SQL
is issued from Python.
"""

import json
import os
import time

import voyageai
from supabase import create_client

# voyage-3 natively outputs 1024-dimensional embeddings.
MODEL = "voyage-3"
EMBED_DIM = 1024

# --- Voyage client (reads VOYAGE_API_KEY) -----------------------------------
_VOYAGE_KEY = os.environ.get("VOYAGE_API_KEY")
if not _VOYAGE_KEY:
    raise RuntimeError("VOYAGE_API_KEY environment variable is not set")
_voyage = voyageai.Client(api_key=_VOYAGE_KEY)

# --- Supabase client (reads SUPABASE_URL / SUPABASE_KEY) ---------------------
_SUPABASE_URL = os.environ.get("SUPABASE_URL")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not _SUPABASE_URL or not _SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY environment variables must be set")
_sb = create_client(_SUPABASE_URL, _SUPABASE_KEY)


def _embed(text: str, input_type: str, max_retries: int = 5) -> list[float]:
    """Embed one string with Voyage, retrying through the free-tier rate limit.

    input_type is "document" when storing and "query" when searching — Voyage
    embeds the two asymmetrically, which improves retrieval quality.
    """
    for attempt in range(max_retries):
        try:
            result = _voyage.embed([text], model=MODEL, input_type=input_type)
            return result.embeddings[0]
        except voyageai.error.RateLimitError:
            if attempt == max_retries - 1:
                raise
            # Free tier is ~3 requests/minute; wait a full window before retrying.
            wait = 25
            print(f"Voyage rate limited; waiting {wait}s "
                  f"({attempt + 1}/{max_retries - 1})...")
            time.sleep(wait)
    raise RuntimeError("exhausted embedding retries")


def embed_and_store(text: str, source: str, chunk_index: int) -> str:
    """Embed `text` and insert it into the documents table; return the new row id."""
    embedding = _embed(text, input_type="document")
    # pgvector accepts its text input form "[f1,f2,...]"; json.dumps produces exactly that.
    row = {
        "content": text,
        "embedding": json.dumps(embedding),
        "source": source,
        "chunk_index": chunk_index,
    }
    # supabase-py returns the inserted rows in .data (we asked for one).
    inserted = _sb.table("documents").insert(row).execute()
    # id is a bigint; the function contract returns it as a string.
    return str(inserted.data[0]["id"])


def search_similar(query: str, top_k: int = 5) -> list[dict]:
    """Embed `query` and return the top_k most cosine-similar document rows.

    The ranking happens in Postgres via the `match_documents` pgvector function;
    we only call it through the supabase-py RPC client.
    """
    query_embedding = _embed(query, input_type="query")
    response = _sb.rpc(
        "match_documents",
        {
            "query_embedding": query_embedding,
            "match_count": top_k,
            # The deployed function takes a minimum-similarity cutoff; 0.0 keeps
            # every candidate so top_k alone decides how many rows come back.
            "match_threshold": 0.0,
        },
    ).execute()
    # The function already returns id/content/source/chunk_index/similarity.
    return response.data


def delete_test_rows() -> int:
    """Delete demo rows (source == 'test') so repeated runs stay idempotent.

    Returns the number of rows removed.
    """
    # eq() filter + delete; supabase-py returns the deleted rows in .data.
    result = _sb.table("documents").delete().eq("source", "test").execute()
    return len(result.data)


if __name__ == "__main__":
    # Clear rows from previous demo runs first so this script is idempotent.
    removed = delete_test_rows()
    print(f"Cleared {removed} prior test row(s).")

    # Three sentences from clearly different topics so retrieval is unambiguous.
    # All tagged source='test' so delete_test_rows() can clean them up next run.
    samples = [
        ("Dogs typically eat a diet of meat, kibble, and the occasional table scrap.", "test"),
        ("The stock market rallied today as tech earnings beat expectations.", "test"),
        ("Photosynthesis converts sunlight, water, and CO2 into glucose and oxygen.", "test"),
    ]

    print("Storing test sentences...")
    for i, (text, source) in enumerate(samples):
        row_id = embed_and_store(text, source=source, chunk_index=i)
        print(f"  stored id={row_id} [{source}] {text!r}")

    # Query about dog diet — the 'animals' sentence should rank first.
    query = "what do dogs eat?"
    print(f"\nQuery: {query!r}\nTop 3 results:")
    for r in search_similar(query, top_k=3):
        # similarity is cosine similarity (1.0 = identical meaning).
        print(f"  {r['similarity']:.3f} | [{r['source']}] {r['content']!r}")
