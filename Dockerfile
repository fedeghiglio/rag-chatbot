# FastAPI backend (main.py)
FROM python:3.14-slim

# Bring in the uv binary from its official image (no pip bootstrap needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# copy mode avoids hardlink warnings when uv writes across build layers.
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first so this layer is cached unless the manifests change.
# The base image matches pyproject's requires-python (>=3.14), so uv uses the
# container's own Python instead of downloading a managed interpreter.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy the application code (.dockerignore keeps out .venv/.git/.env/etc).
COPY . .

# Put the synced virtualenv on PATH so the bare `uvicorn` below resolves to it.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Python entrypoint reads PORT from the environment directly, bypassing shell
# variable expansion entirely. Railway injects $PORT; falls back to 8000 locally.
CMD ["python", "-c", "import os, uvicorn; uvicorn.run('main:app', host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))"]
