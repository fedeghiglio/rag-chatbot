"""Explore semantic similarity between texts using Voyage AI embeddings.

Note: Anthropic does not expose its own embeddings endpoint — its official
recommendation is Voyage AI. So we use the `voyageai` package (model `voyage-3`)
rather than the Anthropic SDK here. The Anthropic SDK is still used elsewhere in
this project for the LLM/generation side.
"""

import math
import os
import time

import voyageai

# Model name is centralized so it's trivial to bump (e.g. to voyage-3.5) later.
MODEL = "voyage-3"

# Read the API key from the environment — never hardcode secrets.
# voyageai.Client() also reads VOYAGE_API_KEY automatically, but reading it
# explicitly lets us fail fast with a clear message if it's missing.
_API_KEY = os.environ.get("VOYAGE_API_KEY")
if not _API_KEY:
    raise RuntimeError("VOYAGE_API_KEY environment variable is not set")

# A single reusable client; constructing it once avoids re-auth on every call.
_client = voyageai.Client(api_key=_API_KEY)


def embed_text(text: str) -> list[float]:
    """Embed a single string and return its embedding vector."""
    # input_type="document" tells Voyage how the text will be used; for a
    # symmetric similarity comparison either side can use the same type.
    result = _client.embed([text], model=MODEL, input_type="document")
    # result.embeddings is a list (one vector per input); we sent one input.
    return result.embeddings[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of two equal-length vectors (range -1..1)."""
    # Dot product of the two vectors.
    dot = sum(x * y for x, y in zip(a, b))
    # Magnitude (L2 norm) of each vector.
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    # Guard against division by zero for a zero vector.
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def compare(text1: str, text2: str) -> float:
    """Embed both texts and return their cosine similarity score."""
    return cosine_similarity(embed_text(text1), embed_text(text2))


def _embed_many(texts: list[str], max_retries: int = 5) -> list[list[float]]:
    """Embed several strings in ONE API call, returning vectors in input order.

    Voyage's free tier is rate-limited to 3 requests/minute, so we batch every
    text into a single request rather than calling embed_text() per string.
    On the free tier a saturated window still rejects with RateLimitError, so we
    retry with backoff until the per-minute window resets.
    """
    for attempt in range(max_retries):
        try:
            result = _client.embed(texts, model=MODEL, input_type="document")
            return result.embeddings
        except voyageai.error.RateLimitError:
            # Last attempt: let the error propagate instead of silently waiting.
            if attempt == max_retries - 1:
                raise
            # Free tier allows ~1 request per 20s; wait a full window to be safe.
            wait = 25
            print(f"Rate limited; waiting {wait}s before retry "
                  f"({attempt + 1}/{max_retries - 1})...")
            time.sleep(wait)
    # Unreachable, but keeps type checkers happy.
    raise RuntimeError("exhausted embedding retries")


if __name__ == "__main__":
    # Each pair is (text1, text2, note explaining the expected score).
    # The printed score is cosine similarity: ~1.0 means near-identical meaning,
    # ~0.0 means unrelated, negative would mean opposing (rare for short text).
    pairs = [
        ("The dog ran fast", "The puppy sprinted quickly",
         "expect high (~0.85+): same event, synonymous wording"),
        ("The dog ran fast", "quarterly revenue report",
         "expect low (~0.3 or less): unrelated topics"),
        ("I love pizza", "Pizza is my favourite food",
         "expect high: same sentiment about the same thing"),
        ("Machine learning", "Neural networks",
         "expect medium-high: related concepts, not synonyms"),
        ("Hello", "Goodbye",
         "expect medium: opposite intent but shared greeting context"),
    ]

    # Collect every distinct text across all pairs so we embed each only once.
    unique_texts = list({t for pair in pairs for t in pair[:2]})
    # Single batched request → map each text to its embedding vector.
    vectors = dict(zip(unique_texts, _embed_many(unique_texts)))

    for text1, text2, note in pairs:
        # Reuse the cached vectors; cosine_similarity runs locally (no API call).
        score = cosine_similarity(vectors[text1], vectors[text2])
        # Show the score alongside what it means for this pair.
        print(f"{score:.3f}  | {text1!r} vs {text2!r}  -> {note}")
