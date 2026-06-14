# Project: rag-chatbot

## Goal
Build a production RAG chatbot over PDFs. Learning project that will become a portfolio piece and client deliverable.

## Stack
- Python 3.11+
- Package manager: uv (not pip)
- HTTP client: httpx (async)
- Data validation: pydantic v2
- LLM + embeddings: Anthropic SDK
- Database: Supabase (postgres + pgvector)
- API layer: FastAPI
- UI: Streamlit

## Commands
- Install dep: uv add [package]
- Run: python [file].py
- Lint: ruff check .

## Rules
- Async-first: use asyncio and httpx
- Never hardcode API keys — os.environ only
- Type hints on all functions
- Comment every non-obvious line
- No LangChain — raw SDK and SQL only for now
