from dataclasses import replace

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

import app.ai.graph.runner as runner_module
from app.ai.graph.deps import GraphDeps
from app.ai.graph.runner import _lazy_vision_chain, _media_to_prompt_vars, run_complaint
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
    """A seeded database plus a complaint ready to process.

    Assigned to the seeded tenant: route_node treats a missing tenant_id as an
    error (an unscoped query would span every tenant), and a complaint with no
    tenant_id is exactly the shape this fixture used to produce.
    """
    seeded = seed_database(db_session)
    complaint = Complaint(
        tracking_id="CIV-RUNNER01",
        tenant_id=seeded["tenant_id"],
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


async def test_a_geocode_failure_degrades_but_does_not_terminate(env):
    """intake documents geocoding failure as degradation. errors accumulates via a
    reducer and is never cleared, so a conditional edge that checks it kills the
    complaint at the next branch -- for a fault that has nothing to do with it."""
    session, complaint = env
    complaint.latitude = 12.9716
    complaint.longitude = 77.5946
    session.commit()

    def boom(lat, lon):
        raise RuntimeError("nominatim slow")

    deps = replace(_deps(session_factory=lambda: session), geocode=boom)
    await _run(session, complaint, deps)

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.status == "assigned", "a geocode failure should not fail the complaint"
    assert stored.category == "ROADS"
    assert session.query(WorkOrder).count() == 1


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


async def test_a_failed_persist_is_retried_on_the_next_run(env, monkeypatch):
    """The checkpoint and the database are separate stores. A completed thread
    whose persistence failed must not be short-circuited forever. A failure to
    persist leaves a failed AgentRun recording that something was attempted."""
    session, complaint = env
    deps = _deps(session_factory=lambda: session)
    saver = InMemorySaver()

    import app.ai.graph.runner as runner_module

    real_persist = runner_module.persist_result

    def boom(*a, **k):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(runner_module, "persist_result", boom)
    with pytest.raises(RuntimeError):
        await run_complaint(complaint.id, session_factory=lambda: session,
                            deps=deps, checkpointer=saver)

    session.rollback()
    session.expire_all()
    # A failure during persistence now leaves a failed AgentRun recording the
    # attempt, so the failure is visible in the database rather than invisible.
    # This is recoverable: persist_result is idempotent and the sweep finds it again.
    failed_run = session.query(AgentRun).one()
    assert failed_run.status == "failed"
    assert "commit failed" in failed_run.error
    initial_run_id = failed_run.id

    monkeypatch.setattr(runner_module, "persist_result", real_persist)
    await run_complaint(complaint.id, session_factory=lambda: session,
                        deps=deps, checkpointer=saver)

    session.expire_all()
    # Two runs total: the failed one from persistence, plus the successful retry.
    assert session.query(AgentRun).count() == 2, "the retry should add a new run"
    final_run = session.query(AgentRun).filter(AgentRun.id != initial_run_id).one()
    assert final_run.status == "completed"
    assert session.query(Complaint).one().status == "assigned"


async def test_a_tenant_less_complaint_fails_routing_instead_of_spanning_every_tenant(env):
    """Complaint.tenant_id is nullable and route_node used to treat None as 'no
    filter', so the query spanned every tenant and the complaint was routed to
    whichever tenant's department happened to list the category first."""
    session, complaint = env
    complaint.tenant_id = None
    session.commit()

    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    run = session.query(AgentRun).one()
    assert "route: complaint has no tenant_id" in run.error
    order = session.query(WorkOrder).one()
    assert order.contractor_id is None


def test_a_traversal_path_raises_rather_than_reading(tmp_path, monkeypatch):
    """file_path comes from the database and is never trusted. Path(...).name
    strips directory components, so an ordinary '../../x' collapses harmlessly
    -- but a file_path of '..' survives .name unchanged and, joined onto the
    upload root and resolved, lands outside it. That must be rejected, not read."""
    from app.config import settings

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    with pytest.raises(ValueError, match="escapes the upload root"):
        _media_to_prompt_vars({"file_path": ".."})


def test_an_oversized_image_is_rejected_without_being_read(tmp_path, monkeypatch):
    from app.config import settings

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    big = upload_dir / "big.jpg"
    big.write_bytes(b"x" * (runner_module.MAX_IMAGE_BYTES + 1))
    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))

    with pytest.raises(ValueError, match="too large"):
        _media_to_prompt_vars({"file_path": "big.jpg"})


def test_all_three_upload_resolvers_use_the_same_path(monkeypatch):
    """main.py, media.py, and runner.py must all resolve upload_dir identically."""
    from app.config import settings
    import app.main as main_module
    import app.services.media as media_module

    # The resolver path in Settings.upload_path
    config_resolved = settings.upload_path
    # The mount path in main.py
    main_path = settings.upload_path
    # The store path in media.py
    media_path = media_module.UPLOAD_ROOT
    # The vision adapter path in runner.py (implicit via _media_to_prompt_vars)
    runner_path = settings.upload_path

    assert config_resolved == main_path
    assert main_path == media_path
    assert media_path == runner_path


def test_the_vision_chain_is_not_built_until_something_invokes_it(monkeypatch):
    """build_deps runs on every complaint, media or not. Building the real
    vision chain means constructing an LLM client -- wasted work, and a wasted
    failure mode, for the overwhelmingly common no-media complaint."""
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return RunnableLambda(lambda payload: {"seen": payload})

    monkeypatch.setattr(runner_module, "_vision_chain", counting)

    lazy = _lazy_vision_chain()
    assert calls["n"] == 0, "the real chain was built before anything invoked it"

    assert lazy.invoke({"file_path": "a.jpg"}) == {"seen": {"file_path": "a.jpg"}}
    assert calls["n"] == 1

    lazy.invoke({"file_path": "b.jpg"})
    assert calls["n"] == 1, "the chain should be built once and reused"


async def test_streaming_with_empty_node_return_completes(env):
    """A node returning {} or None produces an update that _publish_progress
    must handle without crashing. This must not fail the run."""
    session, complaint = env
    updates_seen = []

    async def capture_update(node: str, update: dict) -> None:
        updates_seen.append((node, update))

    # Use the real graph but with a mock checkpointer
    deps = _deps(session_factory=lambda: session)
    saver = InMemorySaver()

    # Run twice: first time to populate checkpoint, second to replay notify
    # (which returns {} on the replay path)
    for run_num in range(2):
        state = await run_complaint(
            complaint.id,
            session_factory=lambda: session,
            deps=deps,
            checkpointer=saver,
            on_update=capture_update,
        )
        assert state["complaint_id"] == complaint.id

    session.expire_all()
    # Verify the run completed and is recorded
    run = session.query(AgentRun).one()
    assert run.status == "completed"
    assert session.query(Complaint).one().status == "assigned"


@pytest.mark.xfail(strict=True, reason="route retrieves from Task 2")
async def test_evidence_is_persisted_as_retrieved_chunk_rows(env):
    from app.db.models.ai import RetrievedChunk as RetrievedChunkRow
    from tests.ai.graph.test_retrieval import FakeRetriever, _hit

    session, complaint = env
    retriever = FakeRetriever([_hit("Public Works owns roads.", "sop_roads.md", ["Roads SOP", "Ownership"])])
    await _run(session, complaint, _deps(session_factory=lambda: session, policy_retriever=retriever))

    rows = session.query(RetrievedChunkRow).all()
    assert rows, "route retrieved evidence, so a row must exist"
    assert {r.node for r in rows} <= {"route", "work_order", "assess_risk", "investigate"}
    assert all(r.source and r.chunk_id and r.snippet for r in rows)
    stored = session.query(Complaint).one()
    assert stored.evidence and stored.evidence[0]["source"] == "sop_roads.md"


async def test_re_running_does_not_duplicate_retrieved_chunk_rows(env):
    from app.db.models.ai import RetrievedChunk as RetrievedChunkRow
    from tests.ai.graph.test_retrieval import FakeRetriever, _hit

    session, complaint = env
    retriever = FakeRetriever([_hit("Public Works owns roads.", "sop_roads.md", ["Roads SOP", "Ownership"])])
    deps = _deps(session_factory=lambda: session, policy_retriever=retriever)
    await _run(session, complaint, deps)
    first = session.query(RetrievedChunkRow).count()
    await _run(session, complaint, deps)
    assert session.query(RetrievedChunkRow).count() == first


@pytest.mark.xfail(strict=True, reason="route retrieves from Task 2")
async def test_a_broken_retriever_degrades_but_does_not_terminate(env):
    from tests.ai.graph.test_retrieval import FakeRetriever

    session, complaint = env
    retriever = FakeRetriever(raises=RuntimeError("index not built"))
    await _run(session, complaint, _deps(session_factory=lambda: session, policy_retriever=retriever))
    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.status == "assigned"
    run = session.query(AgentRun).one()
    assert "retrieval unavailable" in (run.error or "")


def test_the_lazy_retriever_loads_once_and_reports_a_failed_load_every_time():
    from app.ai.graph.runner import LazyRetriever

    loads = []
    def loader():
        loads.append(1)
        raise FileNotFoundError("no index")
    lazy = LazyRetriever(loader)
    for _ in range(2):
        try:
            lazy.search("q", k=1, fetch_k=1, filters=None)
        except FileNotFoundError:
            pass
    assert len(loads) == 2, "a failed load must be retried, not cached as a permanent failure"

    good = []
    class Good:
        def search(self, *a, **k): return good
    lazy = LazyRetriever(lambda: Good())
    assert lazy.search("q", k=1, fetch_k=1, filters=None) is good
    assert lazy.search("q", k=1, fetch_k=1, filters=None) is good


async def test_streaming_observer_exception_does_not_fail_the_run(env):
    """If on_update raises, the observer failure must not crash the run."""
    session, complaint = env

    async def boom(node: str, update: dict) -> None:
        raise RuntimeError("observer crashed")

    deps = _deps(session_factory=lambda: session)
    saver = InMemorySaver()

    state = await run_complaint(
        complaint.id,
        session_factory=lambda: session,
        deps=deps,
        checkpointer=saver,
        on_update=boom,
    )

    session.expire_all()
    # The run must complete despite the observer crashing
    assert state["complaint_id"] == complaint.id
    run = session.query(AgentRun).one()
    assert run.status == "completed"
    assert session.query(Complaint).one().status == "assigned"
