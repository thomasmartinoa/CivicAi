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
UNFINISHED = ("submitted",)

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


async def _run_one(complaint_id: str) -> None:
    """Execute one complaint through the graph. Logs exceptions without propagating."""
    from app.ai.graph.runner import run_complaint

    try:
        await run_complaint(complaint_id, session_factory=SessionLocal)
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
    """Complaint ids the graph never finished. Called at startup."""
    from app.db.models.complaint import Complaint

    session = session_factory()
    try:
        pending = (
            session.query(Complaint.id)
            .filter(Complaint.status.in_(UNFINISHED))
            .all()
        )
        return [row.id for row in pending]
    finally:
        session.close()
