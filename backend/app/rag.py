"""RAG generation layer: retrieve relevant chunks, then have Claude answer from them.

Pulls the most similar document chunks from Supabase (via db.search_similar) and
asks Claude to answer using ONLY those documents via the native citations API. Claude
can only cite passages it was actually given — no free-text chunk numbering, no
citation drift.
"""

import os

import anthropic

from .db import search_similar

# Haiku 4.5 — fast and cheap, which suits short grounded answers over retrieved
# context. Pinned to the exact dated snapshot.
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

# Fail fast with a clear message rather than letting the SDK error obscurely later.
if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
# Bare constructor reads ANTHROPIC_API_KEY from the environment.
_client = anthropic.Anthropic()

# Drop the old citation-format instruction; the citations API handles attribution
# structurally. Only the grounding / refusal contract remains here.
SYSTEM_PROMPT = (
    "You are a precise document assistant. Answer the user's question using ONLY "
    "the provided documents. If the documents do not contain the information needed "
    "to answer the question, say so explicitly — do not use outside knowledge."
)


def answer(question: str, top_k: int = 5) -> dict:
    """Answer `question` from the top_k most similar stored chunks.

    Returns {answer, sources, question, chunks_used}.

    sources is a list of {source, chunk_index, cited_text, similarity} — one entry
    per citation Claude made. A single chunk cited for two distinct passages produces
    two entries but is counted once in chunks_used.
    """
    # 1. Retrieve the most relevant chunks (db's RPC filters by similarity threshold).
    chunks = search_similar(question, top_k=top_k)

    # 2. Nothing retrieved → don't call Claude; there's no context to ground on.
    if not chunks:
        return {
            "answer": (
                "I don't have enough information in the uploaded documents "
                "to answer this question."
            ),
            "sources": [],
            "question": question,
            "chunks_used": 0,
        }

    # 3. Build one document block per chunk. Custom-content source (type: "content")
    # prevents the API from re-chunking our already-sized 512-token windows.
    # citations: {enabled: True} must appear on every block (all-or-none rule).
    doc_blocks: list[dict] = [
        {
            "type": "document",
            "source": {
                "type": "content",
                "content": [{"type": "text", "text": c["content"]}],
            },
            "title": c["source"],
            # context is a free-text hint surfaced in the raw citation object;
            # embedding the DB chunk_index here makes debug inspection easier.
            "context": f"chunk_index {c['chunk_index']}",
            "citations": {"enabled": True},
        }
        for c in chunks
    ]

    # 4. User message: document blocks first, then the question as a plain text block.
    user_content: list[dict] = [*doc_blocks, {"type": "text", "text": question}]

    # 5. Call Claude. No beta header needed — citations is GA.
    response = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    # 6. Parse the response. The API splits the answer into multiple text blocks;
    # blocks that draw from a document carry a .citations list. Each citation has
    # cited_text and document_index (0-based into our doc_blocks / chunks list).
    answer_parts: list[str] = []
    sources: list[dict] = []
    cited_indices: set[int] = set()

    for block in response.content:
        if block.type != "text":
            continue
        answer_parts.append(block.text)
        # block.citations is None when this text span has no citations.
        if not block.citations:
            continue
        for cit in block.citations:
            idx = cit.document_index  # maps back to chunks[idx]
            cited_indices.add(idx)
            sources.append({
                "source": chunks[idx]["source"],
                "chunk_index": chunks[idx]["chunk_index"],
                "cited_text": cit.cited_text,
                "similarity": chunks[idx]["similarity"],
            })

    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "question": question,
        # Count distinct documents actually cited, not just retrieved.
        "chunks_used": len(cited_indices),
    }


if __name__ == "__main__":
    questions = [
        # In-scope: should answer with cited passages from the constitutional AI paper.
        "What is constitutional AI and why was it developed?",
        # Off-topic: should produce a grounded refusal (not a geography hallucination).
        "What is the capital of France?",
    ]

    for q in questions:
        result = answer(q)
        print("=" * 70)
        print(f"Q: {result['question']}")
        print(f"\n{result['answer']}\n")
        print(f"Cited passages ({result['chunks_used']} unique chunks):")
        for s in result["sources"]:
            preview = s["cited_text"][:100].replace("\n", " ")
            print(f"  [{s['source']} chunk {s['chunk_index']}] {preview!r}")
        print()
