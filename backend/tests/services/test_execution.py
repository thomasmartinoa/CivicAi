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
