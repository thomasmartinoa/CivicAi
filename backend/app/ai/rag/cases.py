"""Resolved complaints as retrievable precedent.

The policy corpus says what should happen; a case record says what did. Each
resolved complaint becomes one chunk — description plus real outcome — so
assess_risk can calibrate against outcomes in the same category and district
instead of constants. One record is one chunk on purpose: splitting it would
separate the problem from its resolution.

The collection lives in its own index directory. FaissStore.save overwrites
whatever directory it is given, so sharing one with the policy corpus would
wipe it on every rebuild.
"""

from collections.abc import Callable
from pathlib import Path

from app.ai.rag.chunking import Chunk, chunk_record
from app.ai.rag.embeddings import Embedder
from app.ai.rag.ingest import IngestReport, _sync_collection
from app.ai.rag.retrievers import BM25Retriever, DenseRetriever, HybridRetriever
from app.ai.rag.store import FaissStore

CASES_COLLECTION = "cases"


def case_record_text(complaint, work_order) -> str:
    """Plain prose, because it is embedded and shown to the model verbatim."""
    hours = (work_order.completed_at - work_order.created_at).total_seconds() / 3600
    # The estimate is the fallback, not the headline: what a case teaches is
    # what the work actually cost.
    cost = work_order.actual_cost if work_order.actual_cost is not None else work_order.estimated_cost
    cost_text = f"₹{cost:,.0f}" if cost is not None else "cost not recorded"
    contractor = work_order.contractor.name if work_order.contractor else "no contractor"
    return (
        f"{complaint.category or 'UNCATEGORISED'} complaint in {complaint.district or 'unknown district'}: "
        f"{complaint.description}\n"
        f"Outcome: resolved in {hours:.0f} hours (SLA {work_order.sla_hours}h), "
        f"{cost_text}, by {contractor}."
    )


def case_record_metadata(complaint) -> dict:
    return {
        "collection": CASES_COLLECTION,
        "doc_type": "case",
        "category": complaint.category,
        "district": complaint.district,
        "risk_level": complaint.risk_level,
    }


def _resolved_items(session) -> list[tuple[str, str, list[Chunk]]]:
    """Every completed work order, as (source, text, chunks).

    A work order that is no longer completed simply does not appear here, and
    _sync_collection prunes its rows as an orphan.
    """
    from app.db.models.workflow import WorkOrder

    orders = (
        session.query(WorkOrder)
        .filter(WorkOrder.status == "completed", WorkOrder.completed_at.isnot(None))
        .all()
    )
    items = []
    for order in orders:
        complaint = order.complaint
        source = f"case:{complaint.id}"
        text = case_record_text(complaint, order)
        items.append((source, text, chunk_record(text, source, case_record_metadata(complaint))))
    return items


def ingest_cases(*, embedder: Embedder, index_dir: Path, session_factory: Callable) -> IngestReport:
    session = session_factory()
    try:
        return _sync_collection(session, collection=CASES_COLLECTION, items=_resolved_items(session),
                                embedder=embedder, index_dir=index_dir)
    finally:
        session.close()


def load_cases_retriever(*, embedder: Embedder, index_dir: Path) -> HybridRetriever:
    store = FaissStore.load(index_dir, embedder)
    return HybridRetriever(DenseRetriever(store), BM25Retriever(store.chunks))
