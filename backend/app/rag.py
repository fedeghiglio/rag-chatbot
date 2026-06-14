"""RAG generation layer: retrieve relevant chunks, then have Claude answer from them.

Pulls the most similar document chunks from Supabase (via db.search_similar) and
asks Claude to answer using ONLY that context, with source citations. Claude is
instructed to refuse rather than invent when the context doesn't cover the question.
"""

import os

import anthropic

from .db import search_similar

# Haiku 4.5 — fast and cheap, which suits short grounded answers over retrieved
# context. Pinned to the exact dated id the task specified.
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

# Fail fast with a clear message rather than letting the SDK error obscurely later.
if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
# Bare constructor reads ANTHROPIC_API_KEY from the environment.
_client = anthropic.Anthropic()

# The grounding contract: answer only from context, cite sources, refuse if absent.
SYSTEM_PROMPT = (
    "You are a precise document assistant. Answer the user's question using ONLY "
    "the context provided. After your answer, list your sources as: "
    "[Source: filename, chunk N]. If the context doesn't contain the answer, say "
    "so explicitly — never make up information."
)


def answer(question: str, top_k: int = 5) -> dict:
    """Answer `question` from the top_k most similar stored chunks.

    Returns {answer, sources, question, chunks_used}. If retrieval finds nothing,
    returns the canned "not enough information" response without calling Claude.
    """
    # 1. Retrieve the most relevant chunks (db's RPC already filters by similarity).
    chunks = search_similar(question, top_k=top_k)

    # 2. Nothing retrieved → don't bother calling Claude; there's no context to ground on.
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

    # 4. Build the context block. Each chunk is labeled with its position AND its
    # real source/chunk_index so Claude can cite "[Source: filename, chunk N]"
    # exactly as the system prompt asks (the bare position alone can't do that).
    context = "\n".join(
        f"[chunk {i}] (Source: {c['source']}, chunk {c['chunk_index']}): {c['content']}"
        for i, c in enumerate(chunks)
    )
    user_message = f"Context:\n{context}\n\nQuestion: {question}"

    # 5. Ask Claude. Non-streaming is fine here — max_tokens is small (1024), well
    # under any HTTP timeout.
    response = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    # Join all text blocks (usually one) into the answer string.
    answer_text = "".join(b.text for b in response.content if b.type == "text")

    # 6. Surface which chunks grounded the answer (for citation/debugging in the UI).
    sources = [
        {
            "source": c["source"],
            "chunk_index": c["chunk_index"],
            "similarity": c["similarity"],
        }
        for c in chunks
    ]
    return {
        "answer": answer_text,
        "sources": sources,
        "question": question,
        "chunks_used": len(chunks),
    }


if __name__ == "__main__":
    questions = [
        "What is constitutional AI and why was it developed?",
        "What are the two phases of the constitutional AI process?",
        # Likely under-covered in the retrieved chunks — exercises the
        # "context doesn't contain the answer" path (Claude should say so).
        "What is RLHF and how does it relate to this paper?",
    ]

    for q in questions:
        result = answer(q)
        print("=" * 70)
        print(f"Q: {result['question']}")
        print(f"\n{result['answer']}\n")
        # Show the chunks that grounded the answer, best similarity first.
        print(f"Sources ({result['chunks_used']} chunks used):")
        for s in result["sources"]:
            print(f"  - {s['source']} chunk {s['chunk_index']} (sim {s['similarity']:.3f})")
        print()
