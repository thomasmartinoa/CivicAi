"""Background jobs on a timer, started from the app's lifespan.

APScheduler's AsyncIOScheduler runs on the API's event loop; each job body is
synchronous SQLAlchemy work, so it is pushed to a thread with asyncio.to_thread
to keep the loop free for requests. One process, one scheduler — the Dockerfile
runs a single worker; with several, every worker would run every job.

Every job body catches its own exceptions. APScheduler would log an uncaught one
and carry on, but the message would not say which job or why, and these jobs fail
for boring operational reasons (no embedder configured, the index directory is
read-only) that someone on call needs named.
"""

import asyncio
import logging
from collections.abc import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

logger = logging.getLogger(__name__)

SLA_INTERVAL_MINUTES = 5
CLUSTER_INTERVAL_MINUTES = 60


def build_scheduler(session_factory: Callable) -> AsyncIOScheduler:
    """Register every enabled job. `background_jobs_enabled` is the master
    switch and is checked by the caller, not here."""
    scheduler = AsyncIOScheduler()

    async def sla_job() -> None:
        from app.services.sla import check_sla_deadlines

        try:
            tick = await asyncio.to_thread(check_sla_deadlines, session_factory=session_factory)
            if tick.warned or tick.urgent or tick.breached:
                logger.info("SLA monitor: %s", tick)
        except Exception:
            logger.exception("SLA monitor tick failed")

    async def cluster_job() -> None:
        from app.services.clustering import detect_clusters

        try:
            tick = await asyncio.to_thread(detect_clusters, session_factory=session_factory)
            if tick.clusters:
                logger.info("cluster detection: %s", tick)
        except Exception:
            logger.exception("cluster detection tick failed")

    async def briefing_job() -> None:
        from app.services.briefing import generate_briefing

        try:
            await asyncio.to_thread(generate_briefing, session_factory=session_factory,
                                    chain=_briefing_chain())
            logger.info("daily briefings written")
        except Exception:
            logger.exception("daily briefing failed")

    async def cases_refresh_job() -> None:
        from app.ai.rag.cases import CASES_COLLECTION, ingest_cases
        from app.ai.rag.embeddings import build_embedder
        from app.ai.rag.ingest import collection_index_dir

        try:
            report = await asyncio.to_thread(
                ingest_cases, embedder=build_embedder(), session_factory=session_factory,
                index_dir=collection_index_dir(settings.rag_index_path, CASES_COLLECTION),
            )
            logger.info("cases index refreshed: %d documents, %d chunks",
                        report.documents, report.chunks)
        except Exception:
            logger.exception("cases index refresh failed")

    # max_instances/coalesce on every job: a slow tick must not stack up behind
    # itself, and a run missed while the process was down is not worth replaying.
    common = {"max_instances": 1, "coalesce": True}

    scheduler.add_job(sla_job, "interval", minutes=SLA_INTERVAL_MINUTES, id="sla_monitor", **common)

    if settings.cluster_detection_enabled:
        scheduler.add_job(cluster_job, "interval", minutes=CLUSTER_INTERVAL_MINUTES,
                          id="cluster_detection", **common)

    if settings.briefing_enabled:
        scheduler.add_job(briefing_job, "cron", hour=settings.briefing_hour, minute=0,
                          id="daily_briefing", **common)

    if settings.cases_refresh_enabled:
        # An hour before the briefing: ingest_cases rewrites the whole index
        # directory, and FaissStore allows concurrent reads but not a write
        # alongside them, so it runs when the fewest complaints are in flight.
        # This is the second reason the single-process caveat above matters.
        scheduler.add_job(cases_refresh_job, "cron", hour=(settings.briefing_hour - 1) % 24,
                          minute=0, id="cases_refresh", **common)

    return scheduler


def _briefing_chain():
    """The narrative chain, or None so the job records a fallback rather than
    failing. Built per run: a scheduled job is not hot enough to cache a client,
    and a key added after boot should be picked up."""
    from app.ai.llm import Task, build_structured, cache_for
    from app.ai.schemas import BriefingNarrative

    try:
        return build_structured(Task.NARRATE, BriefingNarrative, "briefing",
                                cache=cache_for("briefing"))
    except Exception:
        logger.warning("no briefing chain available; the briefing will record a fallback",
                       exc_info=True)
        return None
