"""The endpoints that change something, plus the citizen token.

Phase 4a was read-only until these landed: an officer could see every complaint and
alter nothing. The tests are mostly about what must *not* be writable.
"""

import pytest

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Contractor, Tenant, User
from app.db.models.workflow import WorkOrder
from app.services.auth import create_access_token, create_citizen_token, hash_password


@pytest.fixture
def officer(db_session, client):
    user = db_session.query(User).filter(User.role.in_(("officer", "admin"))).first()
    user.password_hash = hash_password("pw")
    db_session.commit()
    return user


@pytest.fixture
def auth(officer):
    return {"Authorization": f"Bearer {create_access_token(user_id=officer.id, role=officer.role)}"}


@pytest.fixture
def complaint(db_session, officer):
    row = Complaint(tracking_id="CIV-MUTATE01", tenant_id=officer.tenant_id,
                    citizen_email="citizen@example.com", description="a blocked drain",
                    category="WATER", risk_level="high", status="assigned",
                    priority_score=72.0, routing_justification="Water board owns drains [1].")
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def order(db_session, officer, complaint):
    crew = db_session.query(Contractor).filter_by(tenant_id=officer.tenant_id).first()
    crew.active_workload = 3
    row = WorkOrder(complaint_id=complaint.id, tenant_id=officer.tenant_id,
                    status="assigned", sla_hours=24, contractor_id=crew.id,
                    sla_deadline=utcnow())
    db_session.add(row)
    db_session.commit()
    return row


# ── PATCH a complaint ───────────────────────────────────────────────────────


def test_an_officer_can_move_a_complaint_along(client, complaint, auth):
    response = client.patch(f"/admin/complaints/{complaint.id}",
                            json={"status": "resolved"}, headers=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_an_illegal_transition_is_refused_with_the_allowed_set(client, db_session,
                                                               officer, auth):
    """A misdirected PATCH must not drag a rejected complaint back into the queue."""
    rejected = Complaint(tracking_id="CIV-REJECT01", tenant_id=officer.tenant_id,
                         citizen_email="a@b.com", description="a neighbour dispute",
                         status="rejected", terminal_reason="not infrastructure")
    db_session.add(rejected)
    db_session.commit()

    response = client.patch(f"/admin/complaints/{rejected.id}",
                            json={"status": "assigned"}, headers=auth)
    assert response.status_code == 409
    assert "cannot become" in response.json()["detail"]


def test_the_citizens_words_and_the_systems_decision_are_not_writable(client, db_session,
                                                                      complaint, auth):
    """An endpoint that let an officer rewrite these would quietly destroy the audit
    trail the whole citation apparatus exists to produce."""
    client.patch(f"/admin/complaints/{complaint.id}", headers=auth, json={
        "status": "resolved",
        "description": "actually it was nothing",
        "category": "ROADS",
        "risk_level": "low",
        "priority_score": 1.0,
        "routing_justification": "I decided otherwise",
        "citizen_email": "someone@else.com",
    })

    db_session.expire_all()
    stored = db_session.query(Complaint).filter_by(id=complaint.id).one()
    assert stored.description == "a blocked drain"
    assert stored.category == "WATER"
    assert stored.risk_level == "high"
    assert stored.priority_score == 72.0
    assert stored.routing_justification == "Water board owns drains [1]."
    assert stored.citizen_email == "citizen@example.com"
    assert stored.status == "resolved", "the one writable field did change"


def test_reopening_a_resolved_complaint_is_counted(client, db_session, complaint, auth):
    """Work called done that was not is the common case; counting it is what makes a
    reopened complaint distinguishable later from one that went right first time."""
    client.patch(f"/admin/complaints/{complaint.id}", json={"status": "resolved"},
                 headers=auth)
    client.patch(f"/admin/complaints/{complaint.id}", json={"status": "in_progress"},
                 headers=auth)

    db_session.expire_all()
    assert db_session.query(Complaint).filter_by(id=complaint.id).one().reopen_count == 1


def test_another_tenants_complaint_cannot_be_patched(client, db_session, auth):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    theirs = Complaint(tracking_id="CIV-THEIRS02", tenant_id=other.id,
                       citizen_email="a@b.com", description="x", status="assigned")
    db_session.add(theirs)
    db_session.commit()

    assert client.patch(f"/admin/complaints/{theirs.id}", json={"status": "resolved"},
                        headers=auth).status_code == 404


def test_patching_a_complaint_needs_an_officer(client, complaint):
    assert client.patch(f"/admin/complaints/{complaint.id}",
                        json={"status": "resolved"}).status_code == 401


# ── PATCH a work order ──────────────────────────────────────────────────────


def test_completing_a_work_order_is_timestamped_by_the_server(client, db_session,
                                                              order, auth):
    """Every SLA figure is computed from completed_at, so a client-supplied one would
    let anybody with an officer token manufacture a compliance record."""
    response = client.patch(f"/admin/work-orders/{order.id}", headers=auth,
                            json={"status": "completed",
                                  "completed_at": "2020-01-01T00:00:00Z"})
    assert response.status_code == 200

    db_session.expire_all()
    stored = db_session.query(WorkOrder).filter_by(id=order.id).one()
    assert stored.completed_at is not None
    assert stored.completed_at.year == utcnow().year, "the 2020 timestamp was ignored"


def test_completing_frees_the_contractor_and_reopening_re_occupies_them(
        client, db_session, order, auth):
    crew_id = order.contractor_id

    client.patch(f"/admin/work-orders/{order.id}", json={"status": "completed"},
                 headers=auth)
    db_session.expire_all()
    assert db_session.get(Contractor, crew_id).active_workload == 2

    client.patch(f"/admin/work-orders/{order.id}", json={"status": "in_progress"},
                 headers=auth)
    db_session.expire_all()
    assert db_session.get(Contractor, crew_id).active_workload == 3


def test_completing_twice_does_not_double_count_the_workload(client, db_session,
                                                             order, auth):
    """A repeated PATCH must not drive the count negative."""
    crew_id = order.contractor_id
    for _ in range(3):
        client.patch(f"/admin/work-orders/{order.id}", json={"status": "completed"},
                     headers=auth)
    db_session.expire_all()
    assert db_session.get(Contractor, crew_id).active_workload == 2


def test_reopening_clears_the_completion_timestamp(client, db_session, order, auth):
    """Otherwise the order reads as finished and in progress at once, and the median
    resolution time counts the job twice."""
    client.patch(f"/admin/work-orders/{order.id}", json={"status": "completed"},
                 headers=auth)
    client.patch(f"/admin/work-orders/{order.id}", json={"status": "in_progress"},
                 headers=auth)

    db_session.expire_all()
    assert db_session.query(WorkOrder).filter_by(id=order.id).one().completed_at is None


def test_the_acting_officer_is_recorded_on_the_row(client, db_session, order, officer, auth):
    """The log is not what an officer will be asked to produce six months later."""
    client.patch(f"/admin/work-orders/{order.id}", json={"status": "completed"},
                 headers=auth)
    db_session.expire_all()
    assert db_session.query(WorkOrder).filter_by(id=order.id).one().officer_id == officer.id


def test_an_illegal_work_order_transition_is_refused(client, db_session, order, auth):
    order.status = "cancelled"
    db_session.commit()
    response = client.patch(f"/admin/work-orders/{order.id}",
                            json={"status": "completed"}, headers=auth)
    assert response.status_code == 409


def test_a_work_order_in_another_tenant_is_not_found(client, db_session, order, auth):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    order.tenant_id = other.id
    db_session.commit()

    assert client.patch(f"/admin/work-orders/{order.id}", json={"status": "completed"},
                        headers=auth).status_code == 404


# ── the approve-email path the frontend uses ────────────────────────────────


def test_the_frontends_approve_email_path_works_and_ignores_its_body(
        client, db_session, complaint, auth):
    """Approving is a signature on the text that is stored. Accepting a body here
    would let the client approve wording the server never saw."""
    complaint.email_draft = "Dear Water Board, the drain at ... [1]"
    db_session.commit()

    response = client.post(f"/admin/complaints/{complaint.id}/approve-email",
                           json={"email_draft": "something I wrote myself"},
                           headers=auth)
    assert response.status_code == 200
    assert response.json()["approved"] is True

    db_session.expire_all()
    stored = db_session.query(Complaint).filter_by(id=complaint.id).one()
    assert stored.email_draft == "Dear Water Board, the drain at ... [1]"


# ── the citizen token ───────────────────────────────────────────────────────


def test_my_complaints_ignores_the_email_in_the_query_string(client, db_session, complaint):
    """The v1 frontend calls /complaints/my?email=<address>, which is the whole OTP
    flow undone. The address comes from the token; the parameter is discarded."""
    db_session.add(Complaint(tracking_id="CIV-NOTYOURS", citizen_email="victim@example.com",
                             description="somebody else's complaint", status="assigned"))
    db_session.commit()

    token = create_citizen_token("citizen@example.com")
    body = client.get("/complaints/my?email=victim@example.com",
                      headers={"Authorization": f"Bearer {token}"}).json()

    assert [c["tracking_id"] for c in body] == ["CIV-MUTATE01"]


def test_my_complaints_needs_a_token(client):
    assert client.get("/complaints/my?email=citizen@example.com").status_code == 401


def test_an_officer_token_is_not_a_citizen_token(client, officer):
    """An officer reading one citizen's complaints should go through the admin API,
    where it is logged against their account."""
    token = create_access_token(user_id=officer.id, role=officer.role)
    assert client.get("/complaints/my",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_citizen_token_is_not_an_officer_token(client):
    """And it must not open the admin API either."""
    token = create_citizen_token("citizen@example.com")
    assert client.get("/admin/complaints",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_verifying_an_otp_returns_a_usable_token(client, db_session, complaint, monkeypatch):
    import re
    captured = []
    monkeypatch.setattr("app.services.notify._send_email",
                        lambda to, subject, body: captured.append(body))

    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    code = re.search(r"\b(\d{6})\b", captured[0]).group(1)

    # The frontend posts this field as `otp`, not `code`.
    verified = client.post("/complaints/verify-otp",
                           json={"email": "citizen@example.com", "otp": code}).json()
    assert verified["token_type"] == "bearer"

    mine = client.get("/complaints/my",
                      headers={"Authorization": f"Bearer {verified['access_token']}"})
    assert mine.status_code == 200
    assert [c["tracking_id"] for c in mine.json()] == ["CIV-MUTATE01"]
