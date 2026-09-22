"""Resolved complaints as precedent: what becomes a case, what it reads like,
and the separation between the cases index and the policy index."""

from datetime import timedelta

from app.ai.rag.cases import (
    CASES_COLLECTION, case_record_metadata, case_record_text, ingest_cases, load_cases_retriever,
)
from app.ai.rag.embeddings import FakeEmbedder
from app.db.base import utcnow
from app.db.models.ai import Document, DocumentChunk
from app.db.models.complaint import Complaint
from app.db.models.workflow import WorkOrder
from app.services.seed import seed_database


def _resolved(session, *, description, category="ROADS", district="East", hours=5.0, cost=6300.0, completed=True):
    from uuid import uuid4

    seeded = seed_database(session)
    complaint = Complaint(tracking_id=f"CIV-{uuid4().hex[:8].upper()}", tenant_id=seeded["tenant_id"],
                          citizen_email="a@b.com", description=description, category=category,
                          district=district, risk_level="high", status="resolved" if completed else "assigned")
    session.add(complaint)
    session.flush()
    created = utcnow() - timedelta(hours=hours)
    order = WorkOrder(complaint_id=complaint.id, tenant_id=seeded["tenant_id"], status="completed" if completed else "assigned",
                      sla_hours=24, estimated_cost=5000.0, actual_cost=cost, created_at=created,
                      completed_at=utcnow() if completed else None)
    session.add(order)
    session.commit()
    return complaint, order


def test_a_case_record_states_the_outcome_in_plain_text(db_session):
    complaint, order = _resolved(db_session, description="Deep pothole near the school gate")
    text = case_record_text(complaint, order)
    assert text.startswith("ROADS complaint in East: Deep pothole near the school gate")
    assert "resolved in 5 hours" in text
    assert "₹6,300" in text
    assert "SLA 24h" in text


def test_case_metadata_is_filterable_by_category_and_district(db_session):
    complaint, _ = _resolved(db_session, description="x")
    assert case_record_metadata(complaint) == {
        "collection": CASES_COLLECTION, "doc_type": "case", "category": "ROADS", "district": "East", "risk_level": "high",
    }


def test_only_completed_work_orders_become_cases(db_session, tmp_path):
    _resolved(db_session, description="done one")
    _resolved(db_session, description="still open", completed=False)
    report = ingest_cases(embedder=FakeEmbedder(), index_dir=tmp_path / "cases", session_factory=lambda: db_session)
    assert report.documents == 1 and report.chunks == 1
    docs = db_session.query(Document).filter_by(collection=CASES_COLLECTION).all()
    assert [d.source_path for d in docs][0].startswith("case:")
    assert db_session.query(DocumentChunk).count() == 1


def test_case_ingest_is_idempotent(db_session, tmp_path):
    _resolved(db_session, description="done one")
    kwargs = dict(embedder=FakeEmbedder(), index_dir=tmp_path / "cases", session_factory=lambda: db_session)
    ingest_cases(**kwargs)
    second = ingest_cases(**kwargs)
    assert second.skipped_unchanged == 1 and second.removed == 0


def test_a_reopened_work_order_stops_being_precedent(db_session, tmp_path):
    """Pruning matters here in a way it does not for files: a case can stop
    qualifying without anything being deleted."""
    _resolved(db_session, description="done one")
    kwargs = dict(embedder=FakeEmbedder(), index_dir=tmp_path / "cases", session_factory=lambda: db_session)
    ingest_cases(**kwargs)
    # Re-queried, not reused: ingest_cases closes the session it was handed,
    # which expunges every instance the test was holding.
    order = db_session.query(WorkOrder).one()
    order.status = "assigned"
    order.completed_at = None
    db_session.commit()
    report = ingest_cases(**kwargs)
    assert report.removed == 1 and report.documents == 0
    assert db_session.query(DocumentChunk).count() == 0


def test_the_cases_retriever_filters_by_category(db_session, tmp_path):
    _resolved(db_session, description="Deep pothole near the school gate")
    _resolved(db_session, description="Streetlight dark for a week", category="ELECTRICITY")
    ingest_cases(embedder=FakeEmbedder(), index_dir=tmp_path / "cases", session_factory=lambda: db_session)
    retriever = load_cases_retriever(embedder=FakeEmbedder(), index_dir=tmp_path / "cases")
    hits = retriever.search("pothole", k=5, fetch_k=200, filters={"category": "ELECTRICITY"})
    assert hits and all(h.chunk.metadata["category"] == "ELECTRICITY" for h in hits)
    assert all(h.chunk.source.startswith("case:") for h in hits)


def test_cases_and_policy_indexes_live_in_separate_directories(db_session, tmp_path):
    from app.ai.rag.chunking import CORPUS_DIR
    from app.ai.rag.ingest import COLLECTION, collection_index_dir, ingest_policy_corpus, load_policy_retriever

    base = tmp_path / "index"
    ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=collection_index_dir(base, COLLECTION),
                         session_factory=lambda: db_session, corpus_dir=CORPUS_DIR)
    _resolved(db_session, description="done one")
    ingest_cases(embedder=FakeEmbedder(), index_dir=collection_index_dir(base, CASES_COLLECTION), session_factory=lambda: db_session)
    policy = load_policy_retriever(embedder=FakeEmbedder(), index_dir=collection_index_dir(base, COLLECTION))
    assert len(policy.search("roads", k=100, fetch_k=200)) > 1, "the cases ingest must not have wiped the policy index"
