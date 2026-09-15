"""Three ways to find a chunk, and how to combine them.

Dense retrieval matches meaning; BM25 matches words (with crude plural
stripping so "potholes" and "pothole" count as the same word). Each misses
what the other catches — a rare proper noun the embedding never learned is
trivial for BM25, while two different phrasings of the same idea are trivial
for dense and invisible to BM25. Reciprocal Rank Fusion merges the two
rankings without needing their scores to be comparable, which they are not.

FAISS has no metadata filtering, so every retriever over-fetches `fetch_k`
candidates and filters in Python before taking `k`. Fine below ~10k chunks;
docs/adr/0002 records the tradeoff.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.ai.rag.chunking import Chunk
from app.ai.rag.store import FaissStore

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    source_retriever: str


def matches(chunk: Chunk, filters: dict | None) -> bool:
    if not filters:
        return True
    return all(chunk.metadata.get(key) == value for key, value in filters.items())


def _tokenise(text: str) -> list[str]:
    tokens = _TOKEN.findall(text.lower())
    # Crude plural stripping, not stemming: "potholes" -> "pothole" so BM25
    # treats singular and plural as the same token. Short words are left
    # alone so "bus" and "gas" don't lose their trailing "s".
    return [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens]


class DenseRetriever:
    def __init__(self, store: FaissStore) -> None:
        self._store = store

    def search(self, query: str, *, k: int = 5, fetch_k: int = 50, filters: dict | None = None) -> list[Hit]:
        candidates = self._store.search(query, fetch_k=fetch_k)
        hits = [Hit(c, s, "dense") for c, s in candidates if matches(c, filters)]
        return hits[:k]


class BM25Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._bm25 = BM25Okapi([_tokenise(c.text) for c in chunks]) if chunks else None

    def search(self, query: str, *, k: int = 5, fetch_k: int = 50, filters: dict | None = None) -> list[Hit]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(_tokenise(query))
        ranked = sorted(range(len(self._chunks)), key=lambda i: scores[i], reverse=True)[:fetch_k]
        hits = [
            Hit(self._chunks[i], float(scores[i]), "bm25")
            for i in ranked
            if scores[i] > 0 and matches(self._chunks[i], filters)
        ]
        return hits[:k]


def rrf_merge(rankings: list[list[Hit]], *, rrf_k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion: score = Σ over rankings of 1 / (rrf_k + rank).

    Rank is 1-based. rrf_k=60 is the value from the original paper and damps the
    advantage of being first in any single list. Scores from the inputs are
    ignored on purpose — a cosine and a BM25 score are not comparable."""
    fused: dict[str, float] = defaultdict(float)
    by_id: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            fused[hit.chunk.chunk_id] += 1.0 / (rrf_k + rank)
            by_id.setdefault(hit.chunk.chunk_id, hit.chunk)
    return [
        Hit(by_id[cid], score, "hybrid")
        for cid, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    ]


class HybridRetriever:
    def __init__(self, dense: DenseRetriever, sparse: BM25Retriever) -> None:
        self._dense = dense
        self._sparse = sparse

    def search(self, query: str, *, k: int = 5, fetch_k: int = 50, filters: dict | None = None) -> list[Hit]:
        dense = self._dense.search(query, k=fetch_k, fetch_k=fetch_k, filters=filters)
        sparse = self._sparse.search(query, k=fetch_k, fetch_k=fetch_k, filters=filters)
        return rrf_merge([dense, sparse])[:k]
