# Production image. Serves the API and the frontend; does NOT ingest.
#
# Ingestion (PDF parsing, OCR, embedding) runs on your machine and writes to the same
# database, so this image needs no tesseract, no poppler and no PDF libraries.

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    FASTEMBED_CACHE_PATH=/app/.fastembed_cache \
    PORT=8000

COPY deploy/requirements-runtime.txt /app/deploy/requirements-runtime.txt
RUN pip install --no-cache-dir -r /app/deploy/requirements-runtime.txt

# `ingest` is copied because retrieval imports ingest.embed for the query vector.
# Only that one module is used at runtime; the PDF-facing modules are never imported.
COPY backend /app/backend
COPY ingest /app/ingest
COPY frontend /app/frontend

# Bake the embedding model into the image rather than downloading it on first request.
# Without this, the first search after a cold start pays a ~130MB download, which on a
# free tier that already sleeps means an unusably slow first query.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" \
    || echo "model prefetch skipped; will download on first use"

EXPOSE 8000

# Free hosts assign the port at runtime, so it cannot be baked into CMD.
# Single worker: 512MB does not fit two copies of the embedding model.
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
