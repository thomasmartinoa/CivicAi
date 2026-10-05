"""The dashboard numbers, against a fixture with values chosen so every assertion
is arithmetic rather than a snapshot."""

from datetime import timedelta

import pytest

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Contractor, Tenant
from app.db.models.workflow import WorkOrder
from app.services.analytics import (
    complaint_counts, contractor_performance, resolution_stats, sla_compliance,
)
from app.services.seed import seed_database


@pytest.fixture
def tenant(db_session):
    return seed_database(db_session)["tenant_id"]


def _complaint(db_session, tenant_id, **over):
    from uuid import uuid4

    fields = dict(tracking_id=f"CIV-{uuid4().hex[:8].upper()}", tenant_id=tenant_id,
                  citizen_email="a@b.com", description="x", category="ROADS",
                  risk_level="high", status="assigned")
    fields.update(over)
    complaint = Complaint(**fields)
    db_session.add(complaint)
    db_session.flush()
    return complaint


def _order(db_session, tenant_id, complaint, *, took_hours=None, sla_hours=24,
           status="completed", contractor_id=None, late=False):
    created = utcnow() - timedelta(hours=took_hours or 1)
    completed = utcnow() if took_hours is not None else None
    deadline = created + timedelta(hours=sla_hours)
    if late and completed is not None:
        deadline = created + timedelta(hours=(took_hours or 1) / 2)
    order = WorkOrder(complaint_id=complaint.id, tenant_id=tenant_id, status=status,
                      sla_hours=sla_hours, created_at=created, completed_at=completed,
                      sla_deadline=deadline, contractor_id=contractor_id)
    db_session.add(order)
    db_session.flush()
    return order


# ── counts ──────────────────────────────────────────────────────────────────


def test_counts_break_down_by_status_category_and_risk(db_session, tenant):
    _complaint(db_session, tenant, status="assigned", category="ROADS", risk_level="high")
    _complaint(db_session, tenant, status="assigned", category="WATER", risk_level="high")
    _complaint(db_session, tenant, status="resolved", category="ROADS", risk_level="low")
    db_session.commit()

    counts = complaint_counts(db_session, tenant_id=tenant)
    assert counts.total == 3
    assert counts.by_status == {"assigned": 2, "resolved": 1}
    assert counts.by_category == {"ROADS": 2, "WATER": 1}
    assert counts.by_risk_level == {"high": 2, "low": 1}


def test_unclassified_complaints_do_not_become_a_none_bucket(db_session, tenant):
    """A category of None is "not classified yet", not a category. Showing it as a
    slice called "None" on a pie chart is how a dashboard loses trust."""
    _complaint(db_session, tenant, category=None, risk_level=None, status="submitted")
    db_session.commit()

    counts = complaint_counts(db_session, tenant_id=tenant)
    assert counts.total == 1, "it still counts towards the total"
    assert counts.by_category == {}
    assert counts.by_risk_level == {}


def test_counts_are_scoped_to_the_tenant(db_session, tenant):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    _complaint(db_session, tenant)
    _complaint(db_session, other.id)
    db_session.commit()

    assert complaint_counts(db_session, tenant_id=tenant).total == 1
    assert complaint_counts(db_session, tenant_id=other.id).total == 1


# ── resolution ──────────────────────────────────────────────────────────────


def test_resolution_uses_the_work_order_not_the_complaint(db_session, tenant):
    """Complaint.updated_at carries onupdate=utcnow, so any later edit would move
    the apparent resolution time. Phase 2c hit the same trap in the briefing."""
    complaint = _complaint(db_session, tenant, status="resolved")
    _order(db_session, tenant, complaint, took_hours=6)
    db_session.commit()

    # Touch the complaint long after the work finished.
    complaint.subcategory = "edited later"
    db_session.commit()

    stats = resolution_stats(db_session, tenant_id=tenant)
    assert stats.median_hours == pytest.approx(6, abs=0.1)


def test_the_median_is_the_middle_value_and_averages_an_even_sample(db_session, tenant):
    for hours in (2, 4, 6):
        _order(db_session, tenant, _complaint(db_session, tenant), took_hours=hours)
    db_session.commit()
    assert resolution_stats(db_session, tenant_id=tenant).median_hours == pytest.approx(4, abs=0.1)

    _order(db_session, tenant, _complaint(db_session, tenant), took_hours=8)
    db_session.commit()
    assert resolution_stats(db_session, tenant_id=tenant).median_hours == pytest.approx(5, abs=0.1)


def test_median_resolution_is_none_not_zero_with_nothing_resolved(db_session, tenant):
    """0h would read as instant service rather than no service."""
    _order(db_session, tenant, _complaint(db_session, tenant), status="assigned")
    db_session.commit()

    stats = resolution_stats(db_session, tenant_id=tenant)
    assert stats.completed == 0
    assert stats.median_hours is None
    assert stats.mean_hours is None


def test_the_fastest_and_slowest_bracket_the_median(db_session, tenant):
    for hours in (1, 5, 50):
        _order(db_session, tenant, _complaint(db_session, tenant), took_hours=hours)
    db_session.commit()

    stats = resolution_stats(db_session, tenant_id=tenant)
    assert stats.fastest_hours == pytest.approx(1, abs=0.1)
    assert stats.slowest_hours == pytest.approx(50, abs=0.1)
    assert stats.fastest_hours <= stats.median_hours <= stats.slowest_hours


# ── SLA compliance ──────────────────────────────────────────────────────────


def test_compliance_counts_only_completed_work(db_session, tenant):
    """An order still running is not a breach. Counting it as one would make the
    figure sink and then recover as work finished, which is backwards."""
    _order(db_session, tenant, _complaint(db_session, tenant), took_hours=2)         # met
    _order(db_session, tenant, _complaint(db_session, tenant), took_hours=30, late=True)
    _order(db_session, tenant, _complaint(db_session, tenant), status="assigned")    # running
    db_session.commit()

    compliance = sla_compliance(db_session, tenant_id=tenant)
    assert compliance.measured == 2
    assert (compliance.met, compliance.breached) == (1, 1)
    assert compliance.rate == 0.5


def test_compliance_is_none_not_one_with_nothing_completed(db_session, tenant):
    """1.0 would read as a perfect record rather than an empty one."""
    _order(db_session, tenant, _complaint(db_session, tenant), status="assigned")
    db_session.commit()

    compliance = sla_compliance(db_session, tenant_id=tenant)
    assert compliance.measured == 0
    assert compliance.rate is None


def test_an_order_with_no_deadline_is_not_judged(db_session, tenant):
    order = _order(db_session, tenant, _complaint(db_session, tenant), took_hours=2)
    order.sla_deadline = None
    db_session.commit()
    assert sla_compliance(db_session, tenant_id=tenant).measured == 0


# ── contractors ─────────────────────────────────────────────────────────────


def test_contractor_rows_count_completed_work_and_breaches(db_session, tenant):
    crew = db_session.query(Contractor).filter_by(tenant_id=tenant).first()
    _order(db_session, tenant, _complaint(db_session, tenant), took_hours=4,
           contractor_id=crew.id)
    _order(db_session, tenant, _complaint(db_session, tenant), took_hours=40,
           contractor_id=crew.id, late=True)
    db_session.commit()

    row = next(r for r in contractor_performance(db_session, tenant_id=tenant)
               if r.contractor_id == crew.id)
    assert row.completed == 2
    assert row.breached == 1
    assert row.median_hours == pytest.approx(22, abs=0.5)


def test_a_contractor_with_no_work_is_listed_rather_than_omitted(db_session, tenant):
    """An officer deciding who to assign needs to see the idle crew too."""
    rows = contractor_performance(db_session, tenant_id=tenant)
    assert len(rows) == db_session.query(Contractor).filter_by(tenant_id=tenant).count()
    idle = [r for r in rows if r.completed == 0]
    assert idle, "the seeded contractors have done nothing yet"
    assert all(r.median_hours is None for r in idle)


def test_contractors_are_ordered_busiest_first(db_session, tenant):
    rows = contractor_performance(db_session, tenant_id=tenant)
    workloads = [r.active_workload for r in rows]
    assert workloads == sorted(workloads, reverse=True)


def test_contractor_performance_is_scoped_to_the_tenant(db_session, tenant):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    db_session.add(Contractor(tenant_id=other.id, name="Someone Else's Crew",
                              specializations=["ROADS"], rating=4.0, active_workload=99))
    db_session.commit()

    names = {r.name for r in contractor_performance(db_session, tenant_id=tenant)}
    assert "Someone Else's Crew" not in names
