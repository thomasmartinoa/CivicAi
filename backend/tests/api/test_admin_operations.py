"""The work-order list, the contractor list and the analytics endpoints.

The arithmetic is tested in `tests/services/test_analytics.py`. What is tested here
is the HTTP surface: the auth, the tenant scoping, the pagination, and the fields the
frontend will render — in particular the ones that must arrive as null rather than as
zero.
"""

from datetime import timedelta

import pytest

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Contractor, Tenant, User
from app.db.models.workflow import WorkOrder
from app.services.auth import create_access_token, hash_password

ENDPOINTS = ["/admin/work-orders", "/admin/contractors", "/admin/analytics",
             "/admin/analytics/performance"]


@pytest.fixture
def officer(db_session, client):
    user = db_session.query(User).filter(User.role.in_(("officer", "admin"))).first()
    user.password_hash = hash_password("pw")
    db_session.commit()
    return user


@pytest.fixture
def auth(officer):
    return {"Authorization": f"Bearer {create_access_token(user_id=officer.id, role=officer.role)}"}


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


def _order(db_session, tenant_id, complaint, *, hours_ago=1, sla_hours=24,
           status="assigned", completed=False, contractor_id=None):
    created = utcnow() - timedelta(hours=hours_ago)
    order = WorkOrder(complaint_id=complaint.id, tenant_id=tenant_id, status=status,
                      sla_hours=sla_hours, created_at=created,
                      sla_deadline=created + timedelta(hours=sla_hours),
                      completed_at=utcnow() if completed else None,
                      contractor_id=contractor_id)
    db_session.add(order)
    db_session.flush()
    return order


# ── auth on every endpoint ──────────────────────────────────────────────────


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_endpoint_needs_a_token(client, endpoint):
    assert client.get(endpoint).status_code == 401


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_endpoint_refuses_a_citizen(client, db_session, endpoint):
    citizen = User(email=f"c{endpoint.count('/')}@example.com", name="C", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    token = create_access_token(user_id=citizen.id, role="citizen")
    assert client.get(endpoint, headers={"Authorization": f"Bearer {token}"}).status_code == 403


# ── work orders ─────────────────────────────────────────────────────────────


def test_work_orders_are_ordered_by_deadline(client, db_session, officer, auth):
    """Closest to breaching first: the list is a queue, not an archive."""
    for hours in (1, 20, 10):
        _order(db_session, tenant_id=officer.tenant_id,
               complaint=_complaint(db_session, officer.tenant_id), hours_ago=hours)
    db_session.commit()

    items = client.get("/admin/work-orders", headers=auth).json()["items"]
    deadlines = [i["sla_deadline"] for i in items]
    assert deadlines == sorted(deadlines)


def test_a_work_order_row_names_the_complaint_and_the_crew(client, db_session, officer, auth):
    crew = db_session.query(Contractor).filter_by(tenant_id=officer.tenant_id).first()
    complaint = _complaint(db_session, officer.tenant_id, tracking_id="CIV-WORKORD1")
    _order(db_session, officer.tenant_id, complaint, contractor_id=crew.id)
    db_session.commit()

    row = client.get("/admin/work-orders", headers=auth).json()["items"][0]
    assert row["tracking_id"] == "CIV-WORKORD1"
    assert row["contractor_name"] == crew.name
    assert row["category"] == "ROADS"


def test_work_orders_can_be_filtered_by_sla_state(client, db_session, officer, auth):
    _order(db_session, officer.tenant_id, _complaint(db_session, officer.tenant_id),
           hours_ago=1)      # on_track
    _order(db_session, officer.tenant_id, _complaint(db_session, officer.tenant_id),
           hours_ago=30)     # breached
    db_session.commit()

    breached = client.get("/admin/work-orders?sla_state=breached", headers=auth).json()
    assert breached["total"] == 1
    assert breached["items"][0]["sla_state"] == "breached"


def test_work_orders_are_scoped_to_the_tenant(client, db_session, officer, auth):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    _order(db_session, officer.tenant_id, _complaint(db_session, officer.tenant_id))
    _order(db_session, other.id, _complaint(db_session, other.id))
    db_session.commit()

    assert client.get("/admin/work-orders", headers=auth).json()["total"] == 1


def test_the_work_order_page_size_is_capped(client, auth):
    assert client.get("/admin/work-orders?size=5000", headers=auth).status_code == 422


def test_work_order_pagination_reports_the_total(client, db_session, officer, auth):
    for _ in range(5):
        _order(db_session, officer.tenant_id, _complaint(db_session, officer.tenant_id))
    db_session.commit()

    body = client.get("/admin/work-orders?size=2&page=2", headers=auth).json()
    assert body["total"] == 5 and body["pages"] == 3 and len(body["items"]) == 2


# ── contractors ─────────────────────────────────────────────────────────────


def test_contractors_include_the_idle_ones_with_null_rather_than_zero(client, auth):
    body = client.get("/admin/contractors", headers=auth).json()
    assert body["contractors"], "the seed provides crews"
    idle = [c for c in body["contractors"] if c["completed"] == 0]
    assert idle
    assert all(c["median_hours"] is None for c in idle), (
        "0 hours would read as instant work rather than no work"
    )


def test_performance_and_contractors_return_the_same_shape(client, auth):
    """The frontend calls both. They are one view of the data."""
    assert (client.get("/admin/contractors", headers=auth).json()
            == client.get("/admin/analytics/performance", headers=auth).json())


# ── analytics ───────────────────────────────────────────────────────────────


def test_analytics_reports_the_breakdowns(client, db_session, officer, auth):
    _complaint(db_session, officer.tenant_id, category="ROADS", status="assigned")
    _complaint(db_session, officer.tenant_id, category="WATER", status="resolved")
    db_session.commit()

    body = client.get("/admin/analytics", headers=auth).json()
    assert body["total_complaints"] == 2
    assert body["by_category"] == {"ROADS": 1, "WATER": 1}
    assert body["by_status"] == {"assigned": 1, "resolved": 1}


def test_analytics_sends_null_not_zero_when_nothing_has_resolved(client, db_session,
                                                                 officer, auth):
    """The frontend must render "no data", and it can only do that if the API does
    not pretend to have measured something."""
    _order(db_session, officer.tenant_id, _complaint(db_session, officer.tenant_id))
    db_session.commit()

    body = client.get("/admin/analytics", headers=auth).json()
    assert body["median_resolution_hours"] is None
    assert body["sla_compliance_rate"] is None
    assert body["completed_work_orders"] == 0


def test_analytics_computes_compliance_once_work_completes(client, db_session,
                                                           officer, auth):
    _order(db_session, officer.tenant_id, _complaint(db_session, officer.tenant_id),
           hours_ago=2, status="completed", completed=True)
    db_session.commit()

    body = client.get("/admin/analytics", headers=auth).json()
    assert body["completed_work_orders"] == 1
    assert body["sla_compliance_rate"] == 1.0
    assert body["median_resolution_hours"] == pytest.approx(2, abs=0.2)


def test_analytics_is_scoped_to_the_tenant(client, db_session, officer, auth):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    _complaint(db_session, officer.tenant_id)
    for _ in range(5):
        _complaint(db_session, other.id)
    db_session.commit()

    assert client.get("/admin/analytics", headers=auth).json()["total_complaints"] == 1


def test_an_officer_with_no_tenant_gets_empty_figures_not_everyones(client, db_session,
                                                                    officer, auth):
    _complaint(db_session, officer.tenant_id)
    db_session.commit()
    officer.tenant_id = None
    db_session.commit()

    body = client.get("/admin/analytics", headers=auth).json()
    assert body["total_complaints"] == 0
    assert client.get("/admin/work-orders", headers=auth).json()["total"] == 0
    assert client.get("/admin/contractors", headers=auth).json()["contractors"] == []
