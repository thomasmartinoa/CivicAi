"""Embedding access, with the dimension pinned.

Gemini's embedding model can emit 768, 1536 or 3072 dimensions; Ollama's
nomic-embed-text is 768. Pinning to 768 lets either provider build an index the
other can query, and the model tag stamped into every index makes a mismatch a
loud failure rather than silently wrong nearest neighbours.
"""

import hashlib
from typing import Protocol, runtime_checkable

import numpy as np

from app.config import settings

EMBEDDING_DIM = 768


class NoEmbedderConfigured(RuntimeError):
    pass


@runtime_checkable
class Embedder(Protocol):
    model_tag: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Deterministic, offline, unit-normalised. For tests only.

    Each text seeds a random generator from its own hash, so the same text
    always maps to the same vector and different texts to different vectors —
    enough for retrieval tests to be meaningful without a model.
    """

    model_tag = f"fake@{EMBEDDING_DIM}"

    def embed_query(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        vector = np.random.default_rng(seed).standard_normal(EMBEDDING_DIM)
        vector /= np.linalg.norm(vector)
        return vector.astype("float32").tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


class GeminiEmbedder:
    model_tag: str

    def __init__(self, model: str, api_key: str) -> None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self.model_tag = self.model_tag_for(model)
        self._client = GoogleGenerativeAIEmbeddings(
            model=f"models/{model}",
            google_api_key=api_key,
            output_dimensionality=EMBEDDING_DIM,
        )

    @staticmethod
    def model_tag_for(model: str) -> str:
        return f"{model}@{EMBEDDING_DIM}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(text)


def build_embedder() -> Embedder:
    """The real embedder, or a clear error. Never a silent fallback."""
    if settings.gemini_api_key:
        return GeminiEmbedder(settings.embedding_model, settings.gemini_api_key)
    raise NoEmbedderConfigured(
        "No embedding provider is configured. Set GEMINI_API_KEY."
    )
