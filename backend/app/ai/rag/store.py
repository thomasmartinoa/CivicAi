"""FAISS behind a small, honest interface.

IndexFlatIP over unit vectors is cosine similarity, exact, with no training
step — right for a corpus of a few thousand chunks. FAISS stores vectors only,
so the chunks themselves live in a JSON sidecar in index order; position i in
the index is chunks[i].

The manifest stamps the embedding model tag. Loading an index with a different
embedder is refused: a mismatched model does not error, it returns plausible
wrong neighbours, which is the worst possible failure mode for retrieval. A
sidecar shorter than the index turns a search into an IndexError long after
the corruption happened, so load() checks that the index, chunks, and manifest
agree on count and dimension and refuses to load otherwise.
"""

import json
from dataclasses import asdict
from pathlib import Path

import faiss
import numpy as np

from app.ai.rag.chunking import Chunk
from app.ai.rag.embeddings import EMBEDDING_DIM, Embedder


class IndexModelMismatch(RuntimeError):
    pass


class IndexCorrupt(RuntimeError):
    pass


class FaissStore:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
        self._chunks: list[Chunk] = []

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[Chunk]:
        """The sidecar, in index order. BM25 is built over the same list."""
        return self._chunks

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vectors = np.asarray(self._embedder.embed_documents([c.text for c in chunks]), dtype="float32")
        faiss.normalize_L2(vectors)
        self._index.add(vectors)
        self._chunks.extend(chunks)

    def search(self, query: str, *, fetch_k: int = 50) -> list[tuple[Chunk, float]]:
        if fetch_k <= 0:
            raise ValueError("fetch_k must be positive")
        if not self._chunks:
            return []
        vector = np.asarray([self._embedder.embed_query(query)], dtype="float32")
        faiss.normalize_L2(vector)
        k = min(fetch_k, len(self._chunks))
        scores, ids = self._index.search(vector, k)
        return [(self._chunks[i], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / "index.faiss"))
        (directory / "chunks.json").write_text(
            json.dumps([asdict(c) for c in self._chunks]), encoding="utf-8"
        )
        (directory / "manifest.json").write_text(json.dumps({
            "model_tag": self._embedder.model_tag,
            "dim": EMBEDDING_DIM,
            "count": len(self._chunks),
        }), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path, embedder: Embedder) -> "FaissStore":
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["model_tag"] != embedder.model_tag:
            raise IndexModelMismatch(
                f"index was built with {manifest['model_tag']!r} but the configured "
                f"embedder is {embedder.model_tag!r}; rebuild the index or switch embedder"
            )
        if manifest["dim"] != EMBEDDING_DIM:
            raise IndexCorrupt(
                f"index dim {manifest['dim']}, embedder dim {EMBEDDING_DIM}; rebuild the index"
            )
        store = cls(embedder)
        store._index = faiss.read_index(str(directory / "index.faiss"))
        store._chunks = [Chunk(**c) for c in json.loads((directory / "chunks.json").read_text(encoding="utf-8"))]

        # Check consistency between index, chunks, and manifest
        index_count = store._index.ntotal
        chunks_count = len(store._chunks)
        manifest_count = manifest["count"]

        if not (index_count == chunks_count == manifest_count):
            raise IndexCorrupt(
                f"index has {index_count} vectors, chunks has {chunks_count}, manifest says {manifest_count}"
            )

        return store
