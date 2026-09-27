"""The officer's morning briefing: the day's numbers, written up.

v1's `briefing.py` called `llm_service._has_api_key()`, which is a module-level
function and not a method, so every invocation raised AttributeError. The
enclosing `except Exception` caught it and returned template text. Every officer
briefing that system ever produced was the hardcoded fallback, and nothing
anywhere recorded that — the try/except meant to add resilience hid a total
feature failure for the life of the project.

Two things follow from that. The counts are computed in Python and handed to the
model as given facts, because an officer acts on them. And when the chain fails
the row records `is_fallback=True` and the failure is logged at warning, so a
briefing that is really template text can never again look like a real one.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from app.db.base import utcnow

logger = logging.getLogger(__name__)


@dataclass
class BriefingStats:
    new_complaints: int = 0
    resolved_today: int = 0
    sla_at_risk: int = 0
    escalations_today: int = 0
    clusters_detected: int = 0


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC midnight to midnight. SQLite stores naive datetimes, so the bounds
    are naive too and every comparison stays in one timezone."""
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def gather_stats(session, *, tenant_id: str, day: date) -> BriefingStats:
    """Count the day. No model: these are facts the narrative is given."""
    from app.db.models.complaint import Complaint
    from app.db.models.workflow import Escalation, WorkOrder
    from app.services.sla import WARNING_AT, elapsed_fraction

    start, end = _day_bounds(day)

    new_complaints = (
        session.query(Complaint)
        .filter(Complaint.tenant_id == tenant_id,
                Complaint.created_at >= start, Complaint.created_at < end)
        .count()
    )
    resolved_today = (
        session.query(Complaint)
        .filter(Complaint.tenant_id == tenant_id, Complaint.status == "resolved",
                Complaint.updated_at >= start, Complaint.updated_at < end)
        .count()
    )
    escalations_today = (
        session.query(Escalation)
        .join(Complaint, Escalation.complaint_id == Complaint.id)
        .filter(Complaint.tenant_id == tenant_id,
                Escalation.escalated_at >= start, Escalation.escalated_at < end)
        .count()
    )
    clusters_detected = (
        session.query(WorkOrder)
        .filter(WorkOrder.tenant_id == tenant_id, WorkOrder.is_cluster.is_(True),
                WorkOrder.created_at >= start, WorkOrder.created_at < end)
        .count()
    )
    # The warning band is defined once, in services/sla.py: the briefing must not
    # disagree with the emails the citizen is already getting.
    sla_at_risk = sum(
        1 for order in _open_orders(session, tenant_id)
        if elapsed_fraction(order, utcnow()) >= WARNING_AT
    )
    return BriefingStats(new_complaints=new_complaints, resolved_today=resolved_today,
                         sla_at_risk=sla_at_risk, escalations_today=escalations_today,
                         clusters_detected=clusters_detected)


def _open_orders(session, tenant_id: str) -> list:
    from app.db.models.workflow import WorkOrder
    from app.services.sla import OPEN_STATUSES

    return (
        session.query(WorkOrder)
        .filter(WorkOrder.tenant_id == tenant_id, WorkOrder.status.in_(OPEN_STATUSES),
                WorkOrder.sla_deadline.isnot(None))
        .all()
    )


def fallback_narrative(stats: BriefingStats) -> str:
    """What the officer reads when the model is unavailable.

    It states every number, because a fallback that only apologises is worse
    than no briefing: the officer still has a day to run.
    """
    return (
        f"{stats.new_complaints} new complaints were logged, {stats.resolved_today} were resolved, "
        f"and {stats.sla_at_risk} work orders are past half their response window. "
        f"{stats.escalations_today} complaints were escalated and {stats.clusters_detected} grouped "
        "work orders were opened. (Narrative unavailable: the summary model could not be reached, "
        "so these are the raw counts.)"
    )


def _render(narrative) -> str:
    """The stored text: the summary, then the priorities as a list."""
    lines = [narrative.summary.strip()]
    if narrative.priorities:
        lines.append("")
        lines.extend(f"- {p}" for p in narrative.priorities[:3])
    return "\n".join(lines)


def _stats_table(stats: BriefingStats) -> str:
    return "\n".join([
        f"- new complaints: {stats.new_complaints}",
        f"- resolved: {stats.resolved_today}",
        f"- work orders past half their window: {stats.sla_at_risk}",
        f"- escalations: {stats.escalations_today}",
        f"- grouped work orders opened: {stats.clusters_detected}",
    ])


def _at_risk_list(session, tenant_id: str) -> str:
    from app.services.sla import WARNING_AT, elapsed_fraction

    lines = []
    for order in _open_orders(session, tenant_id):
        fraction = elapsed_fraction(order, utcnow())
        if fraction >= WARNING_AT:
            tracking = order.complaint.tracking_id if order.complaint else order.id
            lines.append(f"- {tracking}: {fraction:.0%} of the window used")
    return "\n".join(lines) or "- none"


def _cluster_list(session, tenant_id: str, day: date) -> str:
    from app.db.models.workflow import WorkOrder

    start, end = _day_bounds(day)
    orders = (
        session.query(WorkOrder)
        .filter(WorkOrder.tenant_id == tenant_id, WorkOrder.is_cluster.is_(True),
                WorkOrder.created_at >= start, WorkOrder.created_at < end)
        .all()
    )
    lines = [f"- {o.cluster_size} sites grouped under "
             f"{o.complaint.tracking_id if o.complaint else o.complaint_id}" for o in orders]
    return "\n".join(lines) or "- none"


def generate_briefing(
    *,
    session_factory: Callable,
    tenant_id: str | None = None,
    day: date | None = None,
    chain=None,
    retriever=None,
):
    """Write one briefing per tenant for `day`, or for every tenant when
    `tenant_id` is None. Returns the last row written, which is what the
    single-tenant callers and the tests want.

    Idempotent on (tenant, day): the 08:00 job retrying, or an officer asking
    again, updates that morning's row rather than adding a second one.
    """
    from app.db.models.core import Tenant

    day = day or utcnow().date()
    session = session_factory()
    try:
        tenant_ids = [tenant_id] if tenant_id else [t for t, in session.query(Tenant.id).all()]
        row = None
        for current in tenant_ids:
            row = _briefing_for(session, current, day, chain=chain, retriever=retriever)
        session.commit()
        return row
    finally:
        session.close()


def _briefing_for(session, tenant_id: str, day: date, *, chain, retriever):
    from app.ai.graph.retrieval import format_evidence, retrieve
    from app.db.models.workflow import DailyBriefing

    stats = gather_stats(session, tenant_id=tenant_id, day=day)

    # Retrieval is a soft dependency: an ungrounded briefing is still a real
    # briefing. Only a failed *chain* makes it a fallback.
    policy = retrieve(retriever, "priority bands and response windows by risk level",
                      node="briefing", k=2, filters={"doc_type": "sla_policy"})

    is_fallback = False
    try:
        if chain is None:
            raise RuntimeError("no briefing chain configured")
        narrative = _render(chain.invoke({
            "date": day.isoformat(),
            "stats_table": _stats_table(stats),
            "at_risk_list": _at_risk_list(session, tenant_id),
            "cluster_list": _cluster_list(session, tenant_id, day),
            "evidence": format_evidence(policy.chunks),
        }))
    except Exception as exc:
        # v1 hid exactly this failure for its entire life. Record it twice: in
        # the log for whoever is on call, and on the row for whoever reads it.
        logger.warning("briefing narrative failed for tenant %s: %s", tenant_id, exc, exc_info=True)
        narrative, is_fallback = fallback_narrative(stats), True

    start, end = _day_bounds(day)
    row = (
        session.query(DailyBriefing)
        .filter(DailyBriefing.tenant_id == tenant_id,
                DailyBriefing.brief_date >= start, DailyBriefing.brief_date < end)
        .one_or_none()
    )
    if row is None:
        row = DailyBriefing(tenant_id=tenant_id, brief_date=start, narrative="")
        session.add(row)
    row.new_complaints = stats.new_complaints
    row.resolved_today = stats.resolved_today
    row.sla_at_risk = stats.sla_at_risk
    row.escalations_today = stats.escalations_today
    row.clusters_detected = stats.clusters_detected
    row.narrative = narrative
    row.is_fallback = is_fallback
    session.flush()
    return row
