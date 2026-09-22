"""The SLA monitor: warn, escalate, reassign — each exactly once.

Pure deterministic Python on a timer; no model. v1's version was the most
useful automation in the system and also emailed the citizen every five
minutes for as long as a work order sat in the warning band, because it never
recorded that it had already acted. Here every action is keyed by a
Notification row with a unique dedupe_key, inserted before the email goes out.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.ai.graph.nodes.route import score_contractor
from app.constants import Category
from app.db.base import utcnow
from app.services.notify import _send_email

logger = logging.getLogger(__name__)

WARNING_AT = 0.5
URGENT_AT = 0.75
ESCALATION_LADDER = ("ward", "block", "district", "city")
OPEN_STATUSES = ("created", "assigned", "in_progress")


@dataclass
class SlaTick:
    warned: int = 0
    urgent: int = 0
    breached: int = 0


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo; everything here compares against an aware now."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def elapsed_fraction(order, now: datetime) -> float:
    start = _aware(order.created_at)
    deadline = _aware(order.sla_deadline)
    total = (deadline - start).total_seconds()
    if total <= 0:
        return 1.0
    return (_aware(now) - start).total_seconds() / total


def next_level(current: str) -> str | None:
    index = ESCALATION_LADDER.index(current)
    return ESCALATION_LADDER[index + 1] if index + 1 < len(ESCALATION_LADDER) else None


def _claim(session, complaint_id: str, kind: str, recipient: str, subject: str):
    """Insert the idempotency row and return it. None means a previous tick
    already acted — the unique dedupe_key refused the insert."""
    from app.db.models.workflow import Notification

    row = Notification(
        complaint_id=complaint_id, recipient_email=recipient, notification_type=kind,
        message=subject, is_sent=False, dedupe_key=f"{complaint_id}:{kind}",
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return None
    return row


def _notify(session, complaint, kind: str, subject: str, body: str, send: Callable) -> bool:
    """Claim the action, then try to send. A failed send is logged, not
    retried: the claim stands, so the citizen gets at most one of each."""
    row = _claim(session, complaint.id, kind, complaint.citizen_email, subject)
    if row is None:
        return False
    try:
        send(complaint.citizen_email, subject, body)
        row.is_sent, row.sent_at = True, utcnow()
    except Exception:
        logger.warning("SLA email failed for %s", complaint.tracking_id, exc_info=True)
    session.commit()
    return True


def _escalate_and_reassign(session, order, complaint) -> None:
    from app.db.models.core import Contractor
    from app.db.models.workflow import Escalation

    # Climb from wherever the complaint already is.
    last = (session.query(Escalation).filter_by(complaint_id=complaint.id)
            .order_by(Escalation.escalated_at.desc()).first())
    current = last.to_level if last else ESCALATION_LADDER[0]
    target = next_level(current)
    if target is not None:
        session.add(Escalation(complaint_id=complaint.id, from_level=current, to_level=target,
                               reason=f"SLA breached on work order {order.id}"))

    # Next-best contractor by the same score route_node uses, excluding the current one.
    category = Category(complaint.category) if complaint.category else None
    candidates = [c for c in session.query(Contractor).filter_by(tenant_id=order.tenant_id).all()
                  if c.id != order.contractor_id]
    if category and candidates:
        best = max(candidates, key=lambda c: score_contractor(c, category, complaint.district))
        old = session.get(Contractor, order.contractor_id) if order.contractor_id else None
        if old and old.active_workload > 0:
            old.active_workload -= 1
        best.active_workload += 1
        order.contractor_id = best.id


def check_sla_deadlines(*, session_factory: Callable, now: datetime | None = None,
                        send: Callable = _send_email) -> SlaTick:
    from app.db.models.workflow import WorkOrder

    now = now or utcnow()
    tick = SlaTick()
    session = session_factory()
    try:
        orders = (session.query(WorkOrder)
                  .filter(WorkOrder.status.in_(OPEN_STATUSES), WorkOrder.sla_deadline.isnot(None))
                  .all())
        for order in orders:
            complaint = order.complaint
            fraction = elapsed_fraction(order, now)
            tid = complaint.tracking_id
            if fraction >= 1.0:
                if _notify(session, complaint, "sla_breach",
                           f"CivicAI — complaint {tid} has been escalated",
                           f"The response window for {tid} has passed. It has been escalated and reassigned.",
                           send):
                    _escalate_and_reassign(session, order, complaint)
                    session.commit()
                    tick.breached += 1
            elif fraction >= URGENT_AT:
                if _notify(session, complaint, "sla_urgent",
                           f"CivicAI — urgent: complaint {tid} is near its deadline",
                           f"More than 75% of the response window for {tid} has elapsed.",
                           send):
                    tick.urgent += 1
            elif fraction >= WARNING_AT:
                if _notify(session, complaint, "sla_warning",
                           f"CivicAI — complaint {tid} is halfway to its deadline",
                           f"Half of the response window for {tid} has elapsed. Work is in progress.",
                           send):
                    tick.warned += 1
        return tick
    finally:
        session.close()
