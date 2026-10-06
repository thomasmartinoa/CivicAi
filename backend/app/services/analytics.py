"""The numbers behind the officer dashboard.

Here rather than in the route so they can be tested against a fixture with known
values, which makes the assertions arithmetic instead of snapshots.

**Resolution time is measured from the work order, not the complaint.** The obvious
source would be `Complaint.updated_at`, and it is wrong: that column carries
`onupdate=utcnow`, so any later edit to a resolved complaint moves its apparent
resolution time. Phase 2c's carried-forward list records the same trap in the daily
briefing's `resolved_today`. `WorkOrder.created_at` to `completed_at` is the pair
that actually means what it says, and it is only set when work finished.

**Nothing here returns 0 for "no data".** Median resolution over zero resolved work
orders is None, not zero hours, because a dashboard reading "0h" looks like instant
service rather than no service.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class ComplaintCounts:
    total: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_risk_level: dict[str, int] = field(default_factory=dict)


@dataclass
class ResolutionStats:
    completed: int = 0
    median_hours: float | None = None
    mean_hours: float | None = None
    fastest_hours: float | None = None
    slowest_hours: float | None = None


@dataclass
class SlaCompliance:
    measured: int = 0
    """Completed work orders that had a deadline to be judged against."""
    met: int = 0
    breached: int = 0
    rate: float | None = None
    """None when nothing has completed yet — not 1.0, which would read as a perfect
    record rather than an empty one."""


@dataclass
class ContractorRow:
    contractor_id: str
    name: str
    specializations: list[str]
    rating: float | None
    active_workload: int
    completed: int
    median_hours: float | None
    breached: int


def _median(values: list[float]) -> float | None:
    """SQLite has no median, so it is computed here. None on an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _hours(work_order) -> float | None:
    """Hours from dispatch to completion, or None if it is not finished.

    Naive and aware datetimes are both possible — SQLite drops tzinfo — so this
    reuses the same normalisation services/sla.py applies rather than inventing a
    second one.
    """
    from app.services.sla import _aware

    if work_order.completed_at is None or work_order.created_at is None:
        return None
    return (_aware(work_order.completed_at) - _aware(work_order.created_at)).total_seconds() / 3600


def complaint_counts(session: Session, *, tenant_id: str) -> ComplaintCounts:
    """Totals and breakdowns, as three grouped queries rather than one per key."""
    from app.db.models.complaint import Complaint

    def grouped(column) -> dict[str, int]:
        rows = (session.query(column, func.count(Complaint.id))
                .filter(Complaint.tenant_id == tenant_id)
                .group_by(column).all())
        return {key: count for key, count in rows if key is not None}

    total = session.query(func.count(Complaint.id)).filter(
        Complaint.tenant_id == tenant_id).scalar() or 0
    return ComplaintCounts(
        total=total,
        by_status=grouped(Complaint.status),
        by_category=grouped(Complaint.category),
        by_risk_level=grouped(Complaint.risk_level),
    )


def resolution_stats(session: Session, *, tenant_id: str) -> ResolutionStats:
    """How long completed work actually took."""
    from app.db.models.workflow import WorkOrder

    orders = (session.query(WorkOrder)
              .filter(WorkOrder.tenant_id == tenant_id,
                      WorkOrder.status == "completed",
                      WorkOrder.completed_at.isnot(None))
              .all())
    hours = [h for h in (_hours(o) for o in orders) if h is not None]
    if not hours:
        return ResolutionStats(completed=len(orders))
    return ResolutionStats(
        completed=len(orders),
        median_hours=_median(hours),
        mean_hours=sum(hours) / len(hours),
        fastest_hours=min(hours),
        slowest_hours=max(hours),
    )


def sla_compliance(session: Session, *, tenant_id: str) -> SlaCompliance:
    """Of the work that finished and had a deadline, how much finished in time.

    Only completed orders are judged. Counting one that is still running as a breach
    would make the figure fall and then recover as work finished, which is the
    opposite of how a compliance number should behave.
    """
    from app.db.models.workflow import WorkOrder
    from app.services.sla import _aware

    orders = (session.query(WorkOrder)
              .filter(WorkOrder.tenant_id == tenant_id,
                      WorkOrder.status == "completed",
                      WorkOrder.completed_at.isnot(None),
                      WorkOrder.sla_deadline.isnot(None))
              .all())
    if not orders:
        return SlaCompliance()
    met = sum(1 for o in orders if _aware(o.completed_at) <= _aware(o.sla_deadline))
    return SlaCompliance(measured=len(orders), met=met, breached=len(orders) - met,
                         rate=met / len(orders))


def contractor_performance(session: Session, *, tenant_id: str) -> list[ContractorRow]:
    """One row per contractor, busiest first.

    Contractors with no completed work are included with None rather than being
    omitted: an officer deciding who to assign needs to see the crew that has done
    nothing as much as the one that has done everything.
    """
    from app.db.models.core import Contractor
    from app.db.models.workflow import WorkOrder
    from app.services.sla import _aware

    contractors = (session.query(Contractor)
                   .filter(Contractor.tenant_id == tenant_id)
                   .order_by(Contractor.name).all())
    orders = (session.query(WorkOrder)
              .filter(WorkOrder.tenant_id == tenant_id,
                      WorkOrder.contractor_id.isnot(None)).all())

    by_contractor: dict[str, list] = {}
    for order in orders:
        by_contractor.setdefault(order.contractor_id, []).append(order)

    rows = []
    for contractor in contractors:
        theirs = by_contractor.get(contractor.id, [])
        completed = [o for o in theirs if o.status == "completed" and o.completed_at]
        hours = [h for h in (_hours(o) for o in completed) if h is not None]
        breached = sum(1 for o in completed
                       if o.sla_deadline and _aware(o.completed_at) > _aware(o.sla_deadline))
        rows.append(ContractorRow(
            contractor_id=contractor.id,
            name=contractor.name,
            specializations=list(contractor.specializations or []),
            rating=contractor.rating,
            active_workload=contractor.active_workload or 0,
            completed=len(completed),
            median_hours=_median(hours),
            breached=breached,
        ))
    return sorted(rows, key=lambda r: (-r.active_workload, r.name))
