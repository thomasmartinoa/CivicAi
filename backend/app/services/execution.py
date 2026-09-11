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


def schedule_complaint_run(complaint_id: str) -> None:
    """Fire the graph without blocking the caller.

    The task is intentionally not awaited. If the process dies before it
    finishes, the startup sweep picks the complaint up again.
    """
    from app.ai.graph.runner import run_complaint

    async def _run() -> None:
        try:
            await run_complaint(complaint_id, session_factory=SessionLocal)
        except Exception:
            logger.exception("complaint run failed for %s", complaint_id)

    asyncio.create_task(_run())


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
