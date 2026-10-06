"""Background execution of the complaint graph.

v1 used FastAPI BackgroundTasks too, and the citizen-facing latency argument for
it was right. What v1 could not do was notice that a run had been interrupted: a
restart mid-pipeline left the complaint at 'submitted' forever with nothing to
retry it. The checkpointer changes that — `resume_incomplete_runs` at startup
re-drives anything left behind, and `run_complaint` resumes rather than replays.
"""

import asyncio
import logging
from collections.abc import Callable

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Statuses meaning "the graph has not reached a conclusion for this complaint".
#
# 'failed' is here, and it was not until a live run showed why. A gas-cylinder leak
# near a bus stand was validated, classified FIRE_HAZARD at 0.99 confidence, and then
# lost because assess_risk got a 503 "experiencing high demand" — a transient
# provider hiccup. The complaint was written 'failed' with no risk level and no work
# order, and nothing ever looked at it again: the checkpointer held everything needed
# to resume, and this tuple did not mention the status it had landed in. The module
# docstring claims the checkpointer fixed exactly this, so the claim was wrong for
# every failure that was not a restart.
UNFINISHED = ("submitted", "failed")

MAX_RESUME_ATTEMPTS = 3
"""How many times a complaint may be re-driven before it is left alone.

Without a bound, a complaint that fails for a permanent reason — a malformed record,
a bug in a node — would be retried on every single restart, for ever. The count comes
from the AgentRun rows already being written for the audit trail, so nothing new has
to be tracked."""

# A restart after an outage can find hundreds of unfinished complaints. Firing
# them all at once would compete with live traffic for the connection pool and
# queue behind the same rate limiter regardless, so drain them a few at a time.
RESUME_CONCURRENCY = 3
_resume_gate = asyncio.Semaphore(RESUME_CONCURRENCY)

# CPython only holds a weak reference to a running task; without this the
# task can be collected mid-flight. The startup sweep is the only backstop
# and it fires on restart, not within a running process.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Create a task and hold it so it cannot be garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _publish_progress(tracking_id: str, node: str, update: dict) -> None:
    """Publish graph progress as a node update with a human summary for the citizen."""
    from app.services.streaming import registry

    decisions = (update or {}).get("decision_log") or []
    await registry.publish(tracking_id, {
        "node": node,
        "summary": decisions[-1].summary if decisions else None,
    })


async def _run_one(complaint_id: str) -> None:
    """Execute one complaint through the graph. Logs exceptions without propagating."""
    from app.ai.graph.runner import run_complaint
    from app.db.models.complaint import Complaint

    # Query the tracking id in a separate session
    session = SessionLocal()
    try:
        complaint = session.query(Complaint).filter(Complaint.id == complaint_id).one_or_none()
        tracking_id = complaint.tracking_id if complaint else None
    finally:
        session.close()

    # Create a callback that publishes to the tracking id if available
    async def on_update(node: str, update: dict) -> None:
        if tracking_id:
            await _publish_progress(tracking_id, node, update)

    try:
        await run_complaint(complaint_id, session_factory=SessionLocal, on_update=on_update)
    except Exception:
        logger.exception("complaint run failed for %s", complaint_id)


async def _run_guarded(complaint_id: str) -> None:
    """Execute one complaint with concurrency gating to avoid stampeding on restart."""
    async with _resume_gate:
        await _run_one(complaint_id)


def schedule_complaint_run(complaint_id: str) -> None:
    """Fire the graph without blocking the caller.

    The task is intentionally not awaited. If the process dies before it
    finishes, the startup sweep picks the complaint up again.
    """
    _spawn(_run_guarded(complaint_id))


def resume_incomplete_runs(session_factory: Callable = SessionLocal) -> list[str]:
    """Complaint ids the graph never finished. Called at startup.

    Includes complaints that reached 'failed', because the overwhelming majority of
    those are a provider being briefly busy rather than anything about the complaint.
    Bounded by MAX_RESUME_ATTEMPTS so a permanently broken one is not re-driven on
    every restart for the rest of the deployment's life.
    """
    from sqlalchemy import func

    from app.db.models.ai import AgentRun
    from app.db.models.complaint import Complaint

    session = session_factory()
    try:
        attempts = (
            session.query(AgentRun.complaint_id, func.count(AgentRun.id).label("n"))
            .group_by(AgentRun.complaint_id)
            .subquery()
        )
        pending = (
            session.query(Complaint.id)
            .outerjoin(attempts, attempts.c.complaint_id == Complaint.id)
            .filter(Complaint.status.in_(UNFINISHED))
            # A complaint with no run rows at all has never been attempted, so the
            # null has to pass rather than be compared away.
            .filter((attempts.c.n.is_(None)) | (attempts.c.n < MAX_RESUME_ATTEMPTS))
            .all()
        )
        abandoned = (
            session.query(func.count(Complaint.id))
            .join(attempts, attempts.c.complaint_id == Complaint.id)
            .filter(Complaint.status.in_(UNFINISHED),
                    attempts.c.n >= MAX_RESUME_ATTEMPTS)
            .scalar()
        ) or 0
        if abandoned:
            # Loud, because each one is a citizen's report that the system has given
            # up on. Nothing else in the application will mention them again.
            logger.error(
                "%d complaint(s) have failed %d or more times and will not be retried; "
                "they need a human to look at them", abandoned, MAX_RESUME_ATTEMPTS,
            )
        return [row.id for row in pending]
    finally:
        session.close()
