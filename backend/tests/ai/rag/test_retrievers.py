from app.ai.rag.chunking import chunk_record
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.retrievers import (
    BM25Retriever, DenseRetriever, Hit, HybridRetriever, matches, rrf_merge,
)
from app.ai.rag.store import FaissStore


def _corpus():
    rows = [
        ("c1", "A deep pothole on the main road near the school gate", "ROADS", "East"),
        ("c2", "Potholes along the highway shoulder after the monsoon", "ROADS", "West"),
        ("c3", "The streetlight on Church Street has been dark for a week", "ELECTRICITY", "East"),
        ("c4", "Sewage overflowing from an open manhole outside the clinic", "SEWAGE", "East"),
        ("c5", "Broken bench and fallen tree in the park", "PUBLIC_SPACES", "West"),
    ]
    return [chunk_record(t, s, {"category": c, "district": d})[0] for s, t, c, d in rows]


def _dense():
    store = FaissStore(FakeEmbedder())
    store.add(_corpus())
    return DenseRetriever(store)


def test_bm25_finds_lexical_matches_the_fake_embedder_cannot():
    """The fake embedder is content-hashed, so 'pothole' and 'potholes' are unrelated
    to it. BM25 tokenises, so the sparse side catches what dense misses. That is the
    argument for hybrid."""
    hits = BM25Retriever(_corpus()).search("pothole", k=2)
    assert {h.chunk.source for h in hits} == {"c1", "c2"}


def test_dense_returns_exact_text_as_top_hit():
    hits = _dense().search("A deep pothole on the main road near the school gate", k=1)
    assert hits[0].chunk.source == "c1"
    assert hits[0].source_retriever == "dense"


def test_metadata_filter_is_applied_after_fetch():
    """FAISS has no filtering; we over-fetch and filter in Python."""
    hits = _dense().search("pothole", k=5, fetch_k=50, filters={"district": "West"})
    assert hits and all(h.chunk.metadata["district"] == "West" for h in hits)


def test_filter_can_empty_the_result_without_raising():
    assert _dense().search("pothole", filters={"district": "Nowhere"}) == []


def test_matches_requires_every_filter_key():
    chunk = _corpus()[0]
    assert matches(chunk, None)
    assert matches(chunk, {"category": "ROADS"})
    assert matches(chunk, {"category": "ROADS", "district": "East"})
    assert not matches(chunk, {"category": "ROADS", "district": "West"})
    assert not matches(chunk, {"missing_key": "x"})


def test_rrf_rewards_appearing_in_both_rankings():
    a = Hit(_corpus()[0], 0.9, "dense")
    b = Hit(_corpus()[1], 0.8, "dense")
    c = Hit(_corpus()[2], 0.7, "dense")
    dense = [a, b, c]
    sparse = [Hit(_corpus()[1], 3.0, "bm25"), Hit(_corpus()[4], 2.0, "bm25")]

    merged = rrf_merge([dense, sparse], k=60)
    # c2 (index 1) is rank 2 in dense and rank 1 in sparse: 1/62 + 1/61 — beats c1's 1/61 alone
    assert merged[0].chunk.source == "c2"
    assert merged[0].source_retriever == "hybrid"
    assert abs(merged[0].score - (1 / 62 + 1 / 61)) < 1e-9


def test_rrf_deduplicates_by_chunk_id():
    hit = Hit(_corpus()[0], 1.0, "dense")
    merged = rrf_merge([[hit], [hit]])
    assert len(merged) == 1


def test_hybrid_surfaces_hits_from_both_rankings():
    """Dense pins c1 (its exact text scores 1.0); BM25 pins c2 through the shared
    token 'pothole'. The fused ranking holds both and labels them 'hybrid'.
    Whether hybrid beats either retriever alone is a Phase 3 eval question with a
    real embedder — the fake one is content-hashed and has no similarity structure."""
    hybrid = HybridRetriever(_dense(), BM25Retriever(_corpus()))
    hits = hybrid.search("A deep pothole on the main road near the school gate", k=2)
    assert {h.chunk.source for h in hits} == {"c1", "c2"}
    assert all(h.source_retriever == "hybrid" for h in hits)


def test_hybrid_respects_filters_on_both_sides():
    hybrid = HybridRetriever(_dense(), BM25Retriever(_corpus()))
    hits = hybrid.search("pothole", k=5, filters={"district": "East"})
    assert hits and all(h.chunk.metadata["district"] == "East" for h in hits)


def test_hit_is_frozen():
    import dataclasses
    assert Hit.__dataclass_params__.frozen
