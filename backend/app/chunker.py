"""Extract text from a PDF and split it into token-based chunks for embedding.

Chunks are sized in tokens (not characters) because embedding models bill and
truncate by tokens, so token-sized chunks map predictably onto model limits.
Token counting uses tiktoken's cl100k_base encoding. Note this is OpenAI's
tokenizer, not Voyage's — here it's only a consistent, deterministic ruler for
deciding chunk boundaries, not an exact count of Voyage tokens.
"""

import os
import sys

import tiktoken
from pypdf import PdfReader
from pypdf.errors import PyPdfError

# Chunking parameters. STEP is how far the window advances each iteration;
# CHUNK_SIZE - OVERLAP guarantees the last OVERLAP tokens of one chunk are the
# first OVERLAP tokens of the next (the overlap preserves context across the cut).
CHUNK_SIZE = 512
OVERLAP = 50
STEP = CHUNK_SIZE - OVERLAP  # 462
# Chunks below this are almost always page furniture (headers/footers/blank
# pages) or a tiny trailing remnant — not worth embedding.
MIN_TOKENS = 50

# Build the encoder once at import time; constructing it per call is wasteful.
_encoder = tiktoken.get_encoding("cl100k_base")


def chunk_pdf(pdf_path: str) -> list[dict]:
    """Extract a PDF's text and return it as overlapping token-sized chunks.

    Each returned dict is {text, source, chunk_index, token_count}.
    """
    # Every real PDF begins with the "%PDF-" magic bytes. Check this first so a
    # non-PDF saved with a .pdf extension (a common case: an HTML error page from
    # a failed/blocked download) fails with a clear message instead of pypdf's
    # cryptic "EOF marker not found" traceback.
    with open(pdf_path, "rb") as fh:
        header = fh.read(5)
    if header != b"%PDF-":
        raise ValueError(
            f"{pdf_path!r} is not a PDF (starts with {header!r}, expected b'%PDF-'). "
            "It looks like an HTML page or a truncated/failed download."
        )

    # A file with the right header can still be corrupt/truncated; surface pypdf's
    # read errors as a clean ValueError rather than an internal stack trace.
    try:
        reader = PdfReader(pdf_path)
    except PyPdfError as exc:
        raise ValueError(f"Could not read {pdf_path!r} as a PDF: {exc}") from exc
    # extract_text() returns None for image-only/blank pages, so coalesce to "".
    # Join with newlines so page boundaries don't fuse the last word of one page
    # into the first word of the next.
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # Tokenize once; we slice this list into windows rather than re-encoding.
    # disallowed_special=() treats sequences like '<|endofprompt|>' that may appear
    # in PDF text as ordinary text instead of raising ValueError on special tokens.
    tokens = _encoder.encode(full_text, disallowed_special=())

    # Filename only — the stored `source` should be portable, not tied to the
    # caller's absolute path on this machine.
    source = os.path.basename(pdf_path)

    chunks: list[dict] = []
    start = 0
    # chunk_index counts only the chunks we actually keep, so indices stay
    # contiguous (0,1,2,...) even when a tiny chunk is skipped.
    chunk_index = 0
    while start < len(tokens):
        window = tokens[start:start + CHUNK_SIZE]
        token_count = len(window)

        # Skip sub-threshold chunks (only the final remnant can be this small,
        # since every interior window is a full CHUNK_SIZE).
        if token_count >= MIN_TOKENS:
            chunks.append({
                # decode turns the token slice back into human-readable text.
                "text": _encoder.decode(window),
                "source": source,
                "chunk_index": chunk_index,
                "token_count": token_count,
            })
            chunk_index += 1

        # Once this window reaches the end of the document, stop — advancing
        # further would only emit a chunk made entirely of the overlap tail
        # (duplicate content with no new tokens).
        if start + CHUNK_SIZE >= len(tokens):
            break
        start += STEP

    return chunks


if __name__ == "__main__":
    # Require the PDF path as the first CLI argument.
    if len(sys.argv) < 2:
        print(f"usage: python {os.path.basename(sys.argv[0])} <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    # Turn the expected failure modes (missing file, non-PDF, corrupt PDF) into a
    # one-line error + non-zero exit instead of an internal traceback.
    try:
        chunks = chunk_pdf(pdf_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        sys.exit(1)

    # Nothing survived the min-token filter (e.g. an empty or image-only PDF).
    if not chunks:
        print(f"No chunks produced from {pdf_path!r} "
              f"(no extractable text, or all chunks < {MIN_TOKENS} tokens).")
        sys.exit(0)

    counts = [c["token_count"] for c in chunks]
    print(f"Total chunks:       {len(chunks)}")
    # Integer-ish average is fine for a summary; round to one decimal.
    print(f"Avg tokens/chunk:   {sum(counts) / len(counts):.1f}")
    print(f"Min chunk size:     {min(counts)} tokens")
    print(f"Max chunk size:     {max(counts)} tokens")
    # Previews are trimmed to 200 chars and have newlines flattened so the
    # terminal output stays on tidy single-ish lines.
    print(f"\nFirst chunk preview (200 chars):\n{chunks[0]['text'][:200]!r}")
    print(f"\nLast chunk preview (200 chars):\n{chunks[-1]['text'][:200]!r}")
