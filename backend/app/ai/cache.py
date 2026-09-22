"""Semantic cache: a near-duplicate prompt returns the stored completion.

An exact-match cache misses the moment a citizen writes "pot hole" instead of
"pothole". This one embeds the prompt variables and returns the stored result
when the nearest previous prompt scores above `threshold` in cosine
similarity. It reuses the FAISS stack: IndexFlatIP over unit vectors is
cosine, and at a few thousand entries a flat index is instant.

One cache per chain. A classification must never be served as a risk
assessment, and the two chains' inputs differ anyway.

In-memory and per-process on purpose: the point is to skip a model call for
the burst of near-identical complaints a single incident produces, not to be a
durable store. hits/misses are exposed so the Phase 3 dashboard can show the
rate.
"""

import json
from collections.abc import Callable
from typing import Any

import faiss
import numpy as np
from langchain_core.runnables import Runnable, RunnableLambda

from app.ai.rag.embeddings import EMBEDDING_DIM, Embedder


def cache_key(payload: dict) -> str:
    """The text that gets embedded: every prompt variable, in a fixed order."""
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


class SemanticCache:
    def __init__(self, embedder: Embedder, *, threshold: float = 0.95, max_entries: int = 1000) -> None:
        self._embedder = embedder
        self._threshold = threshold
        self._max_entries = max_entries
        self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
        # Texts are kept alongside values so the index can be rebuilt after an
        # eviction: position i in the index is _entries[i].
        self._entries: list[tuple[str, Any]] = []
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def _vector(self, text: str) -> np.ndarray:
        vector = np.asarray([self._embedder.embed_query(text)], dtype="float32")
        faiss.normalize_L2(vector)
        return vector

    def get(self, text: str) -> Any | None:
        if not self._entries:
            self.misses += 1
            return None
        scores, ids = self._index.search(self._vector(text), 1)
        score, position = float(scores[0][0]), int(ids[0][0])
        if position < 0 or score < self._threshold:
            self.misses += 1
            return None
        self.hits += 1
        return self._entries[position][1]

    def put(self, text: str, value: Any) -> None:
        self._entries.append((text, value))
        if len(self._entries) > self._max_entries:
            # IndexFlatIP cannot delete one vector, so drop the oldest entry
            # and rebuild the index from the ones that remain. O(n) embeds,
            # but max_entries is small and this runs once per eviction.
            self._entries = self._entries[-self._max_entries:]
            self._index.reset()
            vectors = np.asarray(self._embedder.embed_documents([t for t, _ in self._entries]), dtype="float32")
            faiss.normalize_L2(vectors)
            self._index.add(vectors)
            return
        self._index.add(self._vector(text))


def with_semantic_cache(chain: Runnable, cache: SemanticCache, key: Callable[[dict], str] = cache_key) -> Runnable:
    """Consult the cache before the chain; store the result after."""

    def run(payload: dict):
        text = key(payload)
        cached = cache.get(text)
        if cached is not None:
            return cached
        result = chain.invoke(payload)
        cache.put(text, result)
        return result

    return RunnableLambda(run)
