"""Pluggable text-embedding backends.

Both the pipeline ``embed`` stage (passages) and search query embedding go
through :func:`get_embedder` so the same model — and the e5 ``query: `` /
``passage: `` prefix convention — is used on both sides. The default ``stub``
backend is deterministic and dependency-free; it exists so tests and dev
environments never need torch. Vector dimensionality is always 1024 to match
``Chunk.embedding``.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from django.conf import settings

EMBEDDING_DIM = 1024


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class StubEmbedder:
    """Deterministic hash-seeded unit vectors; same text always maps to the
    same vector, so nearest-neighbour results are stable in tests."""

    def _vector(self, text: str) -> list[float]:
        import numpy as np

        from corpus.arabic import normalize_for_index

        seed = int.from_bytes(
            hashlib.sha256(normalize_for_index(text).encode()).digest()[:4], 'big'
        )
        rng = np.random.RandomState(seed)
        v = rng.standard_normal(EMBEDDING_DIM)
        v /= np.linalg.norm(v)
        return v.tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class E5Embedder:
    """multilingual-e5-large via sentence-transformers (lazy import: torch is a
    pipeline-worker dependency, never a Django one)."""

    MODEL_NAME = 'intfloat/multilingual-e5-large'

    def __init__(self) -> None:
        self._model = None

    def _load(self):  # noqa: ANN202 - SentenceTransformer only in workers
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(
            [f'passage: {t}' for t in texts], normalize_embeddings=True
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        vector = model.encode([f'query: {text}'], normalize_embeddings=True)[0]
        return vector.tolist()


def get_embedder() -> Embedder:
    backend = getattr(settings, 'EMBEDDING_BACKEND', 'stub')
    if backend == 'e5':
        return E5Embedder()
    if backend == 'stub':
        return StubEmbedder()
    raise ValueError(f'Unknown EMBEDDING_BACKEND: {backend!r}')
