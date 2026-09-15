import pytest

from app.ai.rag.chunking import chunk_record
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.store import FaissStore, IndexModelMismatch, IndexCorrupt


def _chunks():
    return [
        chunk_record("A deep pothole on the main road near the school gate", "c1", {"category": "ROADS"}),
        chunk_record("The streetlight on Church Street has been dark for a week", "c2", {"category": "ELECTRICITY"}),
        chunk_record("Sewage overflowing from an open manhole outside the clinic", "c3", {"category": "SEWAGE"}),
    ]


def test_search_returns_the_most_similar_chunk_first():
    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    # The fake embedder is content-seeded, so the exact text is its own nearest neighbour.
    hits = store.search("A deep pothole on the main road near the school gate", fetch_k=3)
    assert hits[0][0].source == "c1"
    assert hits[0][1] > hits[1][1]


def test_scores_are_cosine_similarities():
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    (chunk, score), = store.search("A deep pothole on the main road near the school gate", fetch_k=1)
    assert abs(score - 1.0) < 1e-5, "identical text should score ~1.0 under cosine"


def test_fetch_k_is_capped_at_the_index_size():
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    assert len(store.search("anything", fetch_k=50)) == 1


def test_empty_store_returns_nothing_rather_than_raising():
    assert FaissStore(FakeEmbedder()).search("anything") == []


def test_save_and_load_round_trip(tmp_path):
    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    store.save(tmp_path)

    loaded = FaissStore.load(tmp_path, FakeEmbedder())
    assert len(loaded) == 3
    hits = loaded.search("Sewage overflowing from an open manhole outside the clinic", fetch_k=1)
    assert hits[0][0].source == "c3"
    assert hits[0][0].metadata["category"] == "SEWAGE"


def test_loading_with_a_different_embedder_is_refused(tmp_path):
    """The whole reason the tag exists: silent dimension or model drift returns
    plausible-looking wrong neighbours. It must fail loudly instead."""
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    store.save(tmp_path)

    class OtherEmbedder(FakeEmbedder):
        model_tag = "other-model@768"

    with pytest.raises(IndexModelMismatch, match="fake@768"):
        FaissStore.load(tmp_path, OtherEmbedder())


def test_chunks_property_exposes_the_sidecar_in_index_order():
    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    assert [c.source for c in store.chunks] == ["c1", "c2", "c3"]


def test_manifest_records_what_was_indexed(tmp_path):
    import json

    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    store.save(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest == {"model_tag": "fake@768", "dim": 768, "count": 3}


def test_load_refuses_corrupted_sidecar(tmp_path):
    """A sidecar shorter than the index turns a search into an IndexError long
    after the corruption happened, so load() checks and refuses."""
    import json

    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    store.save(tmp_path)

    # Corrupt the sidecar: keep only the first chunk
    chunks_json = json.loads((tmp_path / "chunks.json").read_text())
    (tmp_path / "chunks.json").write_text(json.dumps(chunks_json[:1]))

    with pytest.raises(IndexCorrupt, match="3"):
        FaissStore.load(tmp_path, FakeEmbedder())


def test_load_refuses_dimension_mismatch(tmp_path):
    import json

    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    store.save(tmp_path)

    # Corrupt the manifest: change dimension
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["dim"] = 512
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(IndexCorrupt, match="512"):
        FaissStore.load(tmp_path, FakeEmbedder())


def test_search_rejects_non_positive_fetch_k():
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])

    with pytest.raises(ValueError, match="fetch_k must be positive"):
        store.search("anything", fetch_k=0)
