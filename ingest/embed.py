"""Local CPU embeddings via FastEmbed.

BAAI/bge-small-en-v1.5, 384 dimensions. Free, runs on CPU, and the same model is used
at ingest time and at query time — which is not optional. Embedding documents with one
model and queries with another produces silently poor retrieval rather than an error.

The model downloads on first use (~130MB) into FASTEMBED_CACHE_PATH.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from backend.app.config import settings

# bge models expect this prefix on QUERIES only, never on documents. Skipping it costs
# a few points of retrieval quality; applying it to documents too is worse.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=settings.embedding_model)


def embed_documents(texts: Iterable[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _model().embed(list(texts))]


def embed_query(text: str) -> list[float]:
    return next(iter(_model().query_embed([text]))).tolist()


def to_pgvector(vec: list[float]) -> str:
    """asyncpg has no native vector codec; pgvector accepts the literal form."""
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
