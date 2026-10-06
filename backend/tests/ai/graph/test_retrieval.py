"""retrieve() is the one seam between the graph and the RAG stack. It must
never raise: a missing index is a soft error, like a failed geocode."""

from app.ai.graph.retrieval import DEFAULT_FETCH_K, RetrievalResult, format_evidence, retrieve
from app.ai.rag.chunking import chunk_record
from app.ai.rag.retrievers import Hit, matches
from app.ai.schemas import RetrievedChunk


class FakeRetriever:
    """Records each call and returns the canned hits that match `filters`, so
    a node that searches once per document type sees the right hit for each
    -- the same post-filter contract as HybridRetriever.
    """

    def __init__(self, hits=None, raises=None):
        self.hits = hits or []
        self.raises = raises
        self.calls = []

    def search(self, query, *, k=5, fetch_k=50, filters=None):
        self.calls.append({"query": query, "k": k, "fetch_k": fetch_k, "filters": filters})
        if self.raises:
            raise self.raises
        return [h for h in self.hits if matches(h.chunk, filters)][:k]


# Maps a fixed source name to the doc_type a real corpus file of that name
# would carry. sop_<category>.md and case:<id> are patterns, not exact names,
# so they are handled separately in _hit below.
_DOC_TYPES = {
    "rate_card.md": "rate_card",
    "sla_policy.md": "sla_policy",
    "category_taxonomy.md": "taxonomy",
    "contractor_scoring.md": "contractor_scoring",
}


def _default_metadata(source: str) -> dict:
    if source.startswith("sop_") and source.endswith(".md"):
        return {"doc_type": "sop", "category": source[len("sop_"):-len(".md")].upper()}
    if source.startswith("case:"):
        return {"doc_type": "case"}
    if source in _DOC_TYPES:
        return {"doc_type": _DOC_TYPES[source]}
    return {}


def _hit(text, source, headers=None, score=0.5, **metadata):
    """A canned Hit. Metadata defaults from the source name (see
    _default_metadata) so tests read naturally -- `_hit(..., "sop_roads.md")`
    is already filterable by `{"doc_type": "sop", "category": "ROADS"}` --
    and any keyword argument here overrides a derived default.
    """
    meta = {**_default_metadata(source), "headers": headers or [], **metadata}
    chunk = chunk_record(text, source, meta)[0]
    return Hit(chunk, score, "hybrid")


def test_hits_become_retrieved_chunks_tagged_with_the_node():
    retriever = FakeRetriever([_hit("Public Works owns roads.", "sop_roads.md", ["Roads SOP", "Ownership"])])
    result = retrieve(retriever, "who owns roads", node="route", k=1)
    assert isinstance(result, RetrievalResult)
    assert result.error is None
    chunk = result.chunks[0]
    assert isinstance(chunk, RetrievedChunk)
    assert chunk.node == "route"
    assert chunk.source == "sop_roads.md"
    assert chunk.snippet == "Public Works owns roads."
    assert chunk.headers == ["Roads SOP", "Ownership"]
    assert chunk.score == 0.5
    assert chunk.chunk_id and chunk.chunk_id.startswith("sop_roads.md#")


def test_filters_and_an_over_fetch_are_passed_through():
    retriever = FakeRetriever()
    retrieve(retriever, "q", node="route", k=2, filters={"doc_type": "sop", "category": "ROADS"})
    call = retriever.calls[0]
    assert call["filters"] == {"doc_type": "sop", "category": "ROADS"}
    assert call["k"] == 2
    # FAISS filters after fetching, so a narrow filter needs a wide fetch (Phase 2a carry-forward).
    assert call["fetch_k"] == DEFAULT_FETCH_K


def test_a_raising_retriever_is_a_soft_error():
    retriever = FakeRetriever(raises=FileNotFoundError("no index"))
    result = retrieve(retriever, "q", node="route")
    assert result.chunks == []
    assert result.error == "route: retrieval unavailable: no index"


def test_a_missing_retriever_is_a_soft_error():
    result = retrieve(None, "q", node="route")
    assert result.chunks == []
    assert "route: retrieval unavailable" in result.error


def test_evidence_is_numbered_and_cites_the_section():
    chunks = [
        RetrievedChunk(node="route", source="sop_roads.md", snippet="Public Works owns roads.",
                       headers=["Roads SOP", "Ownership"]),
        RetrievedChunk(node="route", source="rate_card.md", snippet="| asphalt | ₹450 |"),
    ]
    text = format_evidence(chunks)
    assert text.startswith("[1] sop_roads.md › Roads SOP › Ownership\nPublic Works owns roads.")
    assert "[2] rate_card.md\n| asphalt | ₹450 |" in text


def test_no_evidence_says_so_rather_than_being_blank():
    assert format_evidence([]) == "No supporting documents were retrieved."


def test_citation_is_source_alone_without_headers():
    assert RetrievedChunk(node="x", source="rate_card.md").citation == "rate_card.md"


def test_the_fake_retriever_applies_filters_like_the_real_one():
    retriever = FakeRetriever([
        _hit("| asphalt | ₹450 |", "rate_card.md"),
        _hit("SLA is 48 hours.", "sla_policy.md"),
        _hit("Public Works owns roads.", "sop_roads.md"),
    ])
    result = retriever.search("q", filters={"doc_type": "rate_card"})
    assert [h.chunk.source for h in result] == ["rate_card.md"]

    result = retriever.search("q", filters=None)
    assert len(result) == 3


def test_hit_metadata_is_derived_from_the_source():
    sop_hit = _hit("x", "sop_roads.md")
    assert sop_hit.chunk.metadata["doc_type"] == "sop"
    assert sop_hit.chunk.metadata["category"] == "ROADS"

    case_hit = _hit("x", "case:1", category="ROADS")
    assert case_hit.chunk.metadata["doc_type"] == "case"
    assert case_hit.chunk.metadata["category"] == "ROADS"
