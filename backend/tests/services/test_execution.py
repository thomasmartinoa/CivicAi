import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.db.models.ai import AgentRun
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant
from app.services.seed import seed_database
from app.services.execution import resume_incomplete_runs


@pytest.fixture
def submitted(db_session):
    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    complaint = Complaint(
        tracking_id="CIV-EXEC0001", tenant_id=tenant.id,
        citizen_email="a@b.com",
        description="A large pothole on the main road near the school gate",
    )
    db_session.add(complaint)
    db_session.commit()
    return db_session, complaint.id


async def test_a_node_that_raises_leaves_a_failed_agent_run(submitted):
    """Without this the complaint stays 'submitted' with no record that anything
    was attempted — invisible under background execution."""
    from app.ai.graph.deps import GraphDeps
    from app.ai.graph.runner import run_complaint
    from app.ai.schemas import ValidationResult
    from langchain_core.runnables import RunnableLambda

    session, complaint_id = submitted
    # classify_chain omitted entirely: require() raises inside the node, which is
    # the "a node raised" path this test exists for.
    deps = GraphDeps(
        validate_chain=RunnableLambda(lambda _: ValidationResult(is_valid=True)),
        session_factory=lambda: session,
        notify=lambda **kw: None,
    )

    with pytest.raises(Exception):
        await run_complaint(complaint_id, session_factory=lambda: session,
                            deps=deps, checkpointer=InMemorySaver())

    session.rollback()
    session.expire_all()
    run = session.query(AgentRun).one()
    assert run.status == "failed"
    assert run.error
    assert run.complaint_id == complaint_id


async def test_resume_sweep_finds_complaints_left_unprocessed(submitted):
    """A restart mid-run must not abandon the complaint. v1's BackgroundTasks
    had no way to know a run had been interrupted."""
    session, complaint_id = submitted
    assert complaint_id in resume_incomplete_runs(session_factory=lambda: session)


async def test_resume_sweep_ignores_finished_complaints(submitted):
    session, complaint_id = submitted
    complaint = session.query(Complaint).one()
    complaint.status = "assigned"
    session.commit()
    assert resume_incomplete_runs(session_factory=lambda: session) == []


async def test_resume_sweep_ignores_rejected_complaints(submitted):
    session, complaint_id = submitted
    complaint = session.query(Complaint).one()
    complaint.status = "rejected"
    session.commit()
    assert resume_incomplete_runs(session_factory=lambda: session) == []


async def test_resume_sweep_respects_concurrency_bound(submitted, monkeypatch):
    """A restart after an outage would pile up hundreds of concurrent graph
    executions competing with live traffic. The sweep gates them."""
    import asyncio
    from app.services.execution import RESUME_CONCURRENCY

    session, complaint_id = submitted

    # Create additional unfinished complaints to exceed the concurrency bound.
    for i in range(RESUME_CONCURRENCY + 2):
        session.add(Complaint(
            tracking_id=f"CIV-CONCURRENT-{i:03d}",
            tenant_id=session.query(Tenant).one().id,
            citizen_email=f"citizen{i}@test.com",
            description=f"Complaint {i}",
        ))
    session.commit()

    # Track concurrent execution to verify the gate is active.
    active_count = 0
    max_active = 0
    active_lock = asyncio.Lock()

    async def mock_run_one(complaint_id: str) -> None:
        """Mock that increments on entry, waits, then decrements."""
        nonlocal active_count, max_active
        async with active_lock:
            active_count += 1
            max_active = max(max_active, active_count)
        try:
            await asyncio.sleep(0.01)  # Simulate work
        finally:
            async with active_lock:
                active_count -= 1

    # Patch the internal _run_one function used by _run_guarded.
    from app.services import execution
    monkeypatch.setattr(execution, "_run_one", mock_run_one)

    # Schedule all unfinished complaints. They should not all execute concurrently.
    from app.services.execution import schedule_complaint_run
    for complaint_id in resume_incomplete_runs(session_factory=lambda: session):
        schedule_complaint_run(complaint_id)

    # Wait for all scheduled tasks to complete (with timeout for safety).
    async def wait_for_completion(timeout=5.0):
        start = asyncio.get_event_loop().time()
        while True:
            async with active_lock:
                if active_count == 0 and max_active > 0:
                    return
            if asyncio.get_event_loop().time() - start > timeout:
                break
            await asyncio.sleep(0.001)

    await wait_for_completion()
    assert max_active <= RESUME_CONCURRENCY, \
        f"observed {max_active} concurrent executions, bound is {RESUME_CONCURRENCY}"


def test_a_complaint_that_failed_is_resumed(db_session):
    """Found by a live run. A gas-cylinder leak near a bus stand was validated,
    classified FIRE_HAZARD at 0.99, and then lost because assess_risk got a 503
    "experiencing high demand" — a provider being briefly busy. It was written
    'failed' and nothing ever looked at it again, although the checkpointer held
    everything needed to finish it.
    """
    complaint = Complaint(tracking_id="CIV-FAILED001", citizen_email="a@b.com",
                          description="gas cylinder leaking near the bus stand",
                          category="FIRE_HAZARD", status="failed")
    db_session.add(complaint)
    db_session.commit()

    assert complaint.id in resume_incomplete_runs(session_factory=lambda: db_session)


def test_a_complaint_that_keeps_failing_is_eventually_left_alone(db_session):
    """Without a bound, one that fails for a permanent reason would be re-driven on
    every restart for the rest of the deployment's life."""
    from app.db.base import utcnow
    from app.db.models.ai import AgentRun
    from app.services.execution import MAX_RESUME_ATTEMPTS

    complaint = Complaint(tracking_id="CIV-HOPELESS1", citizen_email="a@b.com",
                          description="something that always breaks", status="failed")
    db_session.add(complaint)
    db_session.flush()
    for _ in range(MAX_RESUME_ATTEMPTS):
        db_session.add(AgentRun(complaint_id=complaint.id, thread_id=complaint.id,
                                status="failed", started_at=utcnow(),
                                finished_at=utcnow(), duration_ms=1, error="boom"))
    db_session.commit()

    assert complaint.id not in resume_incomplete_runs(session_factory=lambda: db_session)


def test_a_complaint_under_the_attempt_limit_is_still_resumed(db_session):
    from app.db.base import utcnow
    from app.db.models.ai import AgentRun

    complaint = Complaint(tracking_id="CIV-ONEMORE01", citizen_email="a@b.com",
                          description="worth one more go", status="failed")
    db_session.add(complaint)
    db_session.flush()
    db_session.add(AgentRun(complaint_id=complaint.id, thread_id=complaint.id,
                            status="failed", started_at=utcnow(), finished_at=utcnow(),
                            duration_ms=1, error="503"))
    db_session.commit()

    assert complaint.id in resume_incomplete_runs(session_factory=lambda: db_session)


def test_a_resolved_complaint_is_never_resumed(db_session):
    """Re-driving a finished complaint would issue a second work order, and
    work_orders.complaint_id is unique, so it would also crash."""
    complaint = Complaint(tracking_id="CIV-DONE00001", citizen_email="a@b.com",
                          description="already dealt with", status="resolved")
    db_session.add(complaint)
    db_session.commit()

    assert complaint.id not in resume_incomplete_runs(session_factory=lambda: db_session)


def test_a_rejected_complaint_is_never_resumed(db_session):
    """A rejection is a conclusion, not a failure — the distinction v1 lost."""
    complaint = Complaint(tracking_id="CIV-NOPE00001", citizen_email="a@b.com",
                          description="a neighbour dispute", status="rejected",
                          terminal_reason="not infrastructure")
    db_session.add(complaint)
    db_session.commit()

    assert complaint.id not in resume_incomplete_runs(session_factory=lambda: db_session)
