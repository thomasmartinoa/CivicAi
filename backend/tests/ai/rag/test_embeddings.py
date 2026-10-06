import math

import pytest

from app.ai.rag import embeddings as embeddings_module
from app.ai.rag.embeddings import (
    EMBEDDING_DIM, Embedder, FakeEmbedder, NoEmbedderConfigured, build_embedder,
)


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def test_fake_embedder_produces_the_pinned_dimension():
    vectors = FakeEmbedder().embed_documents(["a pothole", "a streetlight"])
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
    assert len(FakeEmbedder().embed_query("anything")) == EMBEDDING_DIM


def test_fake_embedder_is_deterministic():
    """Two runs must index identically, or tests become order-dependent."""
    a = FakeEmbedder().embed_query("pothole on the main road")
    b = FakeEmbedder().embed_query("pothole on the main road")
    assert a == b


def test_fake_embedder_is_unit_normalised():
    """IndexFlatIP only computes cosine similarity if inputs are unit vectors."""
    vector = FakeEmbedder().embed_query("pothole")
    assert abs(_norm(vector) - 1.0) < 1e-6


def test_fake_embedder_distinguishes_different_text():
    a = FakeEmbedder().embed_query("pothole")
    b = FakeEmbedder().embed_query("streetlight")
    assert a != b


def test_fake_embedder_satisfies_the_protocol():
    assert isinstance(FakeEmbedder(), Embedder)
    assert FakeEmbedder().model_tag == f"fake@{EMBEDDING_DIM}"


def test_gemini_embedder_tag_carries_model_and_dimension():
    """The tag is what a store checks before loading an index."""
    from app.ai.rag.embeddings import GeminiEmbedder

    assert GeminiEmbedder.model_tag_for("gemini-embedding-001") == "gemini-embedding-001@768"


def test_build_embedder_fails_loudly_with_nothing_configured(monkeypatch):
    monkeypatch.setattr(embeddings_module.settings, "gemini_api_key", None)
    with pytest.raises(NoEmbedderConfigured, match="GEMINI_API_KEY"):
        build_embedder()


def test_build_embedder_does_not_dial_out_at_construction(monkeypatch):
    """Constructing a client must be free; only embedding calls the network."""
    monkeypatch.setattr(embeddings_module.settings, "gemini_api_key", "test-key")
    embedder = build_embedder()
    assert embedder.model_tag == "gemini-embedding-001@768"
