"""Deterministic retrieval recall, offline.

The real measurement needs the real index; these tests cover the scoring and the
cases themselves — in particular that every case's `must_contain` really does appear
in the corpus, since a typo there would make the case unfailable.
"""

import pytest

from app.ai.rag.chunking import load_corpus
from app.evals.retrieval_eval import CASES, RecallCase, evaluate_retrieval
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


def test_every_case_looks_for_text_that_exists_in_the_corpus():
    """A `must_contain` with a typo can never be found, so the case would report a
    permanent miss and nobody would know it was the test that was wrong."""
    corpus = {path.name: text for path, text in load_corpus()}
    for case in CASES:
        haystack = " ".join(corpus.values()).lower()
        assert case.must_contain.lower() in haystack, (
            f"{case.name}: {case.must_contain!r} is nowhere in the corpus"
        )


def test_every_case_names_a_filter_a_node_actually_uses():
    for case in CASES:
        assert "doc_type" in case.filters, case.name


def test_case_names_are_unique():
    assert len({c.name for c in CASES}) == len(CASES)


def test_a_found_chunk_reports_its_rank():
    retriever = FakeRetriever([
        _hit("Barricading and warning signage", "rate_card.md", ["Rate Card", "Unit rates"]),
        _hit("Excavation and trench reinstatement per m3 Rs 900", "rate_card.md",
             ["Rate Card", "Unit rates"]),
    ])
    case = RecallCase(name="t", query="q", filters={"doc_type": "rate_card"},
                      must_contain="Excavation and trench reinstatement", k=3)
    report = evaluate_retrieval(retriever, cases=[case])
    assert report.results[0].found is True
    assert report.results[0].rank == 2
    assert report.recall_at_k == 1.0


def test_a_miss_lists_what_came_back_instead():
    """The list is the useful part: "it missed" is a fact, "it returned the
    Escalation section instead" is a lead."""
    retriever = FakeRetriever([
        _hit("Roads escalate to the ward engineer.", "sop_roads.md", ["Roads SOP", "Escalation"]),
    ])
    case = RecallCase(name="t", query="q", filters={"doc_type": "sop", "category": "ROADS"},
                      must_contain="Public Works")
    report = evaluate_retrieval(retriever, cases=[case])
    result = report.results[0]
    assert result.found is False
    assert result.rank is None
    assert "sop_roads.md › Roads SOP › Escalation" in result.retrieved
    assert "MISSED" in result.summary
    assert report.misses == [result]


def test_recall_ignores_cases_that_could_not_run():
    """A broken index is not a retrieval miss, and averaging it in as one would
    understate recall for a reason that has nothing to do with retrieval."""
    case = RecallCase(name="t", query="q", filters={"doc_type": "rate_card"}, must_contain="x")
    report = evaluate_retrieval(FakeRetriever(raises=RuntimeError("no index")), cases=[case])
    assert report.results[0].error is not None
    assert report.recall_at_k is None
    assert report.misses == []


def test_recall_is_none_rather_than_zero_with_no_cases():
    assert evaluate_retrieval(FakeRetriever(), cases=[]).recall_at_k is None


def test_the_k_the_case_declares_is_the_k_used():
    """The point is to reproduce what the node sees, not a best-case search."""
    retriever = FakeRetriever([
        _hit("first", "rate_card.md"), _hit("second", "rate_card.md"),
        _hit("Excavation and trench reinstatement", "rate_card.md"),
    ])
    case = RecallCase(name="t", query="q", filters={"doc_type": "rate_card"},
                      must_contain="Excavation and trench reinstatement", k=2)
    assert evaluate_retrieval(retriever, cases=[case]).results[0].found is False
    assert retriever.calls[0]["k"] == 2


def test_the_fetch_k_matches_what_the_nodes_use():
    from app.ai.graph.retrieval import DEFAULT_FETCH_K

    retriever = FakeRetriever()
    evaluate_retrieval(retriever, cases=[CASES[0]])
    assert retriever.calls[0]["fetch_k"] == DEFAULT_FETCH_K


def test_no_case_matches_on_a_section_header():
    """Headers live in chunk *metadata*, not in chunk text. A case whose
    must_contain is a header reports a permanent miss while the right chunk is
    coming back at rank 1 — which is exactly what happened to work_order.cluster."""
    from app.ai.rag.chunking import chunk_markdown

    headers = set()
    for path, text in load_corpus():
        for chunk in chunk_markdown(text, path.name):
            headers.update(chunk.metadata.get("headers", []))
    for case in CASES:
        assert case.must_contain not in headers, (
            f"{case.name}: {case.must_contain!r} is a section header, so it is not in "
            "any chunk's text — match on body text instead"
        )
