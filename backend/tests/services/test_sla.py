"""The SLA monitor is deterministic Python on a timer. Each band acts once
per work order, however many times the timer fires — v1's Bug 4."""

from datetime import timedelta

import pytest

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Contractor
from app.db.models.workflow import Escalation, Notification, WorkOrder
from app.services.seed import seed_database
from app.services.sla import (
    ESCALATION_LADDER, URGENT_AT, WARNING_AT, SlaTick, check_sla_deadlines, elapsed_fraction, next_level,
)


@pytest.fixture
def order(db_session):
    seeded = seed_database(db_session)
    roads = [c for c in db_session.query(Contractor).all() if "ROADS" in (c.specializations or [])]
    assert len(roads) >= 2, "the seed must provide two ROADS contractors for reassignment"
    complaint = Complaint(tracking_id="CIV-SLA00001", tenant_id=seeded["tenant_id"], citizen_email="a@b.com",
                          description="pothole", category="ROADS", district=roads[0].zone, status="assigned")
    db_session.add(complaint)
    db_session.flush()
    order = WorkOrder(complaint_id=complaint.id, tenant_id=seeded["tenant_id"], contractor_id=roads[0].id,
                      status="assigned", sla_hours=24, created_at=utcnow(), sla_deadline=utcnow() + timedelta(hours=24))
    db_session.add(order)
    db_session.commit()
    return order


def _tick(session, order, hours, sent):
    return check_sla_deadlines(session_factory=lambda: session, now=order.created_at + timedelta(hours=hours),
                               send=lambda recipient, subject, body: sent.append((recipient, subject)))


def test_elapsed_fraction_is_time_used_over_window(order):
    assert elapsed_fraction(order, order.created_at + timedelta(hours=12)) == pytest.approx(0.5)
    assert elapsed_fraction(order, order.created_at + timedelta(hours=30)) == pytest.approx(1.25)


def test_nothing_happens_before_the_warning_band(db_session, order):
    sent = []
    assert _tick(db_session, order, 6, sent) == SlaTick()
    assert sent == []


def test_a_warning_is_sent_once_however_many_ticks(db_session, order):
    sent = []
    assert _tick(db_session, order, 13, sent) == SlaTick(warned=1)
    for _ in range(5):
        assert _tick(db_session, order, 14, sent) == SlaTick()
    assert len(sent) == 1
    assert db_session.query(Notification).filter_by(dedupe_key=f"{order.complaint_id}:sla_warning").count() == 1


def test_the_urgent_band_sends_its_own_single_email(db_session, order):
    sent = []
    _tick(db_session, order, 13, sent)
    assert _tick(db_session, order, 19, sent) == SlaTick(urgent=1)
    assert _tick(db_session, order, 20, sent) == SlaTick()
    assert [s for _, s in sent] and "urgent" in sent[-1][1].lower()


def test_a_breach_escalates_and_reassigns_once(db_session, order):
    sent = []
    old = order.contractor_id
    old_workload = db_session.get(Contractor, old).active_workload
    assert _tick(db_session, order, 25, sent) == SlaTick(breached=1)
    assert _tick(db_session, order, 26, sent) == SlaTick()

    db_session.expire_all()
    order = db_session.query(WorkOrder).one()
    assert order.contractor_id != old
    escalation = db_session.query(Escalation).one()
    assert (escalation.from_level, escalation.to_level) == (ESCALATION_LADDER[0], ESCALATION_LADDER[1])
    assert db_session.get(Contractor, old).active_workload == max(0, old_workload - 1)
    new = db_session.get(Contractor, order.contractor_id)
    assert new.active_workload >= 1


def test_a_second_breach_climbs_the_ladder(db_session, order):
    """A re-opened or re-deadlined order escalates from where it already is."""
    sent = []
    _tick(db_session, order, 25, sent)
    db_session.expire_all()
    order = db_session.query(WorkOrder).one()
    order.sla_deadline = order.sla_deadline + timedelta(hours=24)
    order.sla_hours = 48
    db_session.query(Notification).filter_by(dedupe_key=f"{order.complaint_id}:sla_breach").delete()
    db_session.commit()
    _tick(db_session, order, 49, sent)
    levels = [(e.from_level, e.to_level) for e in db_session.query(Escalation).order_by(Escalation.escalated_at)]
    assert levels == [("ward", "block"), ("block", "district")]


def test_the_ladder_ends_at_city():
    assert next_level("ward") == "block"
    assert next_level("district") == "city"
    assert next_level("city") is None


def test_completed_orders_are_ignored(db_session, order):
    order.status = "completed"
    db_session.commit()
    sent = []
    assert _tick(db_session, order, 30, sent) == SlaTick()


def test_a_failed_email_still_counts_as_acted(db_session, order):
    """The claim row is what makes an action once-only. If the send raises
    after it is written, a later tick must not retry the email forever."""
    def boom(recipient, subject, body):
        raise RuntimeError("smtp down")

    first = check_sla_deadlines(session_factory=lambda: db_session,
                                now=order.created_at + timedelta(hours=13), send=boom)
    assert first == SlaTick(warned=1)
    row = db_session.query(Notification).filter_by(dedupe_key=f"{order.complaint_id}:sla_warning").one()
    assert row.is_sent is False
    sent = []
    assert _tick(db_session, order, 14, sent) == SlaTick()


def test_the_bands_are_named_constants():
    assert (WARNING_AT, URGENT_AT) == (0.5, 0.75)
