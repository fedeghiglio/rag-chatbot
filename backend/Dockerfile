# FastAPI backend (backend/app/main.py)
# Build context = repo ROOT (railway.toml sets dockerfilePath = "backend/Dockerfile").
# COPY paths are therefore relative to the repo root.
FROM python:3.14-slim

# Bring in the uv binary from its official image (no pip bootstrap needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# copy mode avoids hardlink warnings when uv writes across build layers.
ENV UV_LINK_MODE=copy

WORKDIR /code

# Dependency manifests live in backend/. Copy them first so this layer is cached
# unless they change. Base image matches pyproject's requires-python (>=3.14), so
# uv uses the container's own interpreter rather than downloading one.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy the application package (becomes /code/app, importable as `app`).
COPY backend/app ./app

# Put the synced virtualenv on PATH so `python` below resolves to it.
ENV PATH="/code/.venv/bin:$PATH"

EXPOSE 8000

# Python entrypoint reads PORT from the environment directly, bypassing shell
# variable expansion. Railway injects $PORT; falls back to 8000 locally.
CMD ["python", "-c", "import os, uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))"]
