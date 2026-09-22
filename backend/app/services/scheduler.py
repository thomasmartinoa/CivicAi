"""Background jobs on a timer, started from the app's lifespan.

APScheduler's AsyncIOScheduler runs on the API's event loop; each job body is
synchronous SQLAlchemy work, so it is pushed to a thread with asyncio.to_thread
to keep the loop free for requests. One process, one scheduler — the Dockerfile
runs a single worker; with several, every worker would run every job.
"""

import asyncio
import logging
from collections.abc import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.sla import check_sla_deadlines

logger = logging.getLogger(__name__)

SLA_INTERVAL_MINUTES = 5


def build_scheduler(session_factory: Callable) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def sla_job() -> None:
        try:
            tick = await asyncio.to_thread(check_sla_deadlines, session_factory=session_factory)
            if tick.warned or tick.urgent or tick.breached:
                logger.info("SLA monitor: %s", tick)
        except Exception:
            logger.exception("SLA monitor tick failed")

    # max_instances/coalesce: a slow tick must not stack up behind itself, and
    # a run missed while the process was busy is not worth replaying.
    scheduler.add_job(sla_job, "interval", minutes=SLA_INTERVAL_MINUTES, id="sla_monitor",
                      max_instances=1, coalesce=True)
    return scheduler
