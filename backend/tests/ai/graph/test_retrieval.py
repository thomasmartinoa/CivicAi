"""retrieve() is the one seam between the graph and the RAG stack. It must
never raise: a missing index is a soft error, like a failed geocode."""

from app.ai.graph.retrieval import DEFAULT_FETCH_K, RetrievalResult, format_evidence, retrieve
from app.ai.rag.chunking import chunk_record
from app.ai.rag.retrievers import Hit
from app.ai.schemas import RetrievedChunk


class FakeRetriever:
    """Records the call and returns canned hits. `.search` mirrors HybridRetriever."""

    def __init__(self, hits=None, raises=None):
        self.hits = hits or []
        self.raises = raises
        self.calls = []

    def search(self, query, *, k=5, fetch_k=50, filters=None):
        self.calls.append({"query": query, "k": k, "fetch_k": fetch_k, "filters": filters})
        if self.raises:
            raise self.raises
        return self.hits[:k]


def _hit(text, source, headers=None, score=0.5):
    chunk = chunk_record(text, source, {"headers": headers or [], "doc_type": "sop"})[0]
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
