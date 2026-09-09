from dataclasses import replace

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

from app.ai.graph.deps import GraphDeps
from app.ai.graph.runner import run_complaint
from app.ai.schemas import (
    ClassificationResult, RiskAssessment, ValidationResult, VisionObservation,
)
from app.constants import Category, RiskLevel
from app.db.models.ai import AgentRun, AgentStep
from app.db.models.complaint import Complaint
from app.db.models.workflow import WorkOrder
from app.services.seed import seed_database
from tests.ai.graph.conftest import raises, returns


@pytest.fixture
def env(db_session):
    """A seeded database plus a complaint ready to process."""
    seed_database(db_session)
    complaint = Complaint(
        tracking_id="CIV-RUNNER01",
        citizen_email="a@b.com",
        description="There is a large pothole on the main road near the school gate",
    )
    db_session.add(complaint)
    db_session.commit()
    return db_session, complaint


def _deps(*, valid=True, notified=None, **over):
    return GraphDeps(
        validate_chain=returns(ValidationResult(is_valid=valid, rejection_reason=None if valid else "a neighbour dispute")),
        classify_chain=returns(ClassificationResult(category=Category.ROADS, confidence=0.93)),
        risk_chain=returns(RiskAssessment(priority_score=80, risk_level=RiskLevel.CRITICAL)),
        vision_chain=returns(VisionObservation(text="a pothole", shows_infrastructure_problem=True)),
        notify=(lambda **kw: notified.append(kw)) if notified is not None else (lambda **kw: None),
        **over,
    )


async def _run(session, complaint, deps):
    return await run_complaint(
        complaint.id,
        session_factory=lambda: session,
        deps=deps,
        checkpointer=InMemorySaver(),
    )


async def test_a_valid_complaint_runs_end_to_end(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.category == Category.ROADS.value
    assert stored.risk_level == RiskLevel.CRITICAL.value
    assert stored.priority_score == 80
    assert stored.status == "assigned"
    assert stored.terminal_reason is None


async def test_a_valid_complaint_gets_a_work_order(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    order = session.query(WorkOrder).one()
    assert order.sla_hours == 4
    assert order.sla_deadline is not None
    assert order.estimated_cost > 0


async def test_a_rejected_complaint_is_stored_as_rejected(env):
    """v1's headline bug: a correctly-rejected complaint was written back as
    'submitted', indistinguishable from one that had never been processed."""
    session, complaint = env
    await _run(session, complaint, _deps(valid=False, session_factory=lambda: session))

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.status == "rejected"
    assert "neighbour" in stored.terminal_reason
    assert stored.status != "submitted"


async def test_a_rejected_complaint_gets_no_work_order(env):
    session, complaint = env
    await _run(session, complaint, _deps(valid=False, session_factory=lambda: session))
    assert session.query(WorkOrder).count() == 0


async def test_a_technical_failure_is_distinct_from_a_rejection(env):
    """An outage and a business decision must not look the same afterwards."""
    session, complaint = env
    deps = replace(
        _deps(session_factory=lambda: session),
        classify_chain=raises(RuntimeError("503 from provider")),
    )
    await _run(session, complaint, deps)

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.status == "failed"
    assert stored.terminal_reason is None


async def test_an_agent_run_row_records_the_run(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    run = session.query(AgentRun).one()
    assert run.complaint_id == complaint.id
    assert run.thread_id == complaint.id
    assert run.status == "completed"
    assert run.graph_version
    assert run.duration_ms is not None


async def test_one_agent_step_per_node_in_order(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    steps = session.query(AgentStep).order_by(AgentStep.seq).all()
    assert [s.node for s in steps] == [
        "intake", "validate", "classify", "assess_risk", "route", "work_order", "notify"
    ]
    assert [s.seq for s in steps] == list(range(len(steps)))


async def test_re_running_the_same_complaint_is_idempotent(env):
    """A resumed run replays nodes that already succeeded. It must not email the
    citizen twice, and it must not fail inserting a second work order —
    work_orders.complaint_id is unique."""
    session, complaint = env
    sent = []
    deps = _deps(notified=sent, session_factory=lambda: session)
    saver = InMemorySaver()

    for _ in range(2):
        await run_complaint(
            complaint.id,
            session_factory=lambda: session,
            deps=deps,
            checkpointer=saver,
        )

    session.expire_all()
    assert len(sent) == 1, "the citizen was notified twice"
    assert session.query(WorkOrder).count() == 1, "a duplicate work order was inserted"
    # Not 2: the second invocation lands on an already-completed thread, so
    # _advance short-circuits to the stored snapshot without calling ainvoke,
    # and run_complaint skips persist_result entirely -- nothing new happened,
    # so no second AgentRun is recorded.
    assert session.query(AgentRun).count() == 1, "a completed run should not record a second AgentRun"


async def test_a_completed_run_is_not_re_executed(env):
    """Passing an input restarts the graph from START; only None resumes. Without
    that distinction a 'resume' re-invokes every chain for real and re-appends the
    whole decision log as duplicate AgentStep rows."""
    session, complaint = env
    calls = {"classify": 0}

    def counting(_):
        calls["classify"] += 1
        return ClassificationResult(category=Category.ROADS, confidence=0.93)

    deps = replace(_deps(session_factory=lambda: session),
                   classify_chain=RunnableLambda(counting))
    saver = InMemorySaver()

    for _ in range(3):
        await run_complaint(complaint.id, session_factory=lambda: session,
                            deps=deps, checkpointer=saver)

    session.expire_all()
    assert calls["classify"] == 1, "a completed run was re-executed"
    steps = session.query(AgentStep).all()
    assert len(steps) == 7, f"expected one row per node, got {len(steps)}"
    assert [s.node for s in session.query(AgentStep).order_by(AgentStep.seq).all()] == [
        "intake", "validate", "classify", "assess_risk", "route", "work_order", "notify"
    ]
