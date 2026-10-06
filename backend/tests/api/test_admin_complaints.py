"""The officer's complaint queue and the detail behind it.

Two kinds of test here: the ones about what an officer must see (priority order, the
citations from Phase 2b), and the ones about what they must not (another tenant's
complaints, an unbounded page).
"""

from datetime import timedelta

import pytest
from sqlalchemy import event

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant, User
from app.db.models.workflow import Escalation, WorkOrder
from app.services.auth import create_access_token, hash_password


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
                  citizen_email="a@b.com", description="a pothole on the main road",
                  category="ROADS", risk_level="high", priority_score=50,
                  status="assigned", district="South Bangalore")
    fields.update(over)
    complaint = Complaint(**fields)
    db_session.add(complaint)
    db_session.flush()
    return complaint


# ── what the officer must see ───────────────────────────────────────────────


def test_the_queue_is_ordered_by_priority_then_recency(client, db_session, officer, auth):
    """An officer opens this to answer "what next", not "what happened last"."""
    for score in (10, 90, 50):
        _complaint(db_session, officer.tenant_id, priority_score=score)
    db_session.commit()

    items = client.get("/admin/complaints", headers=auth).json()["items"]
    assert [i["priority_score"] for i in items] == [90, 50, 10]


def test_complaints_with_no_priority_sort_last_rather_than_first(client, db_session, officer, auth):
    """NULL sorts first in SQLite by default, which would put every unprocessed
    complaint above a critical one."""
    _complaint(db_session, officer.tenant_id, priority_score=None, status="submitted")
    _complaint(db_session, officer.tenant_id, priority_score=20)
    db_session.commit()

    items = client.get("/admin/complaints", headers=auth).json()["items"]
    assert items[0]["priority_score"] == 20
    assert items[-1]["priority_score"] is None


def test_the_detail_carries_the_evidence_citations(client, db_session, officer, auth):
    """The first screen on which Phase 2b's grounding is visible to a person."""
    complaint = _complaint(db_session, officer.tenant_id, evidence=[
        {"node": "route", "source": "sop_roads.md", "headers": ["Roads SOP", "Ownership"],
         "snippet": "Public Works owns road surface defects.", "score": 0.03},
    ], routing_justification="Public Works owns road surface defects [1].")
    db_session.commit()

    body = client.get(f"/admin/complaints/{complaint.id}", headers=auth).json()
    assert body["routing_justification"].startswith("Public Works")
    assert body["evidence"][0]["citation"] == "sop_roads.md › Roads SOP › Ownership"
    assert body["evidence"][0]["node"] == "route"


def test_the_detail_includes_the_work_order_and_its_sla_state(client, db_session, officer, auth):
    complaint = _complaint(db_session, officer.tenant_id)
    created = utcnow() - timedelta(hours=20)
    db_session.add(WorkOrder(complaint_id=complaint.id, tenant_id=officer.tenant_id,
                             status="assigned", sla_hours=24, created_at=created,
                             sla_deadline=created + timedelta(hours=24)))
    db_session.commit()

    body = client.get(f"/admin/complaints/{complaint.id}", headers=auth).json()
    assert body["work_order"]["sla_state"] == "urgent", "20 of 24 hours is past 75%"


def test_sla_state_uses_the_same_bands_the_citizen_was_emailed_on(client, db_session, officer, auth):
    """If the screen drew these lines anywhere else, an officer would read "on track"
    for a complaint whose author had already been told it was running late."""
    from app.services.sla import URGENT_AT, WARNING_AT

    cases = {"on_track": 0.1, "warning": WARNING_AT + 0.01, "urgent": URGENT_AT + 0.01,
             "breached": 1.1}
    for expected, fraction in cases.items():
        complaint = _complaint(db_session, officer.tenant_id)
        created = utcnow() - timedelta(hours=24 * fraction)
        db_session.add(WorkOrder(complaint_id=complaint.id, tenant_id=officer.tenant_id,
                                 status="assigned", sla_hours=24, created_at=created,
                                 sla_deadline=created + timedelta(hours=24)))
        db_session.commit()
        body = client.get(f"/admin/complaints/{complaint.id}", headers=auth).json()
        assert body["work_order"]["sla_state"] == expected, (expected, fraction)


def test_a_completed_work_order_is_not_reported_as_breached(client, db_session, officer, auth):
    """Finished late is finished, and an officer scanning for breaches should not be
    shown work that is already done."""
    complaint = _complaint(db_session, officer.tenant_id)
    created = utcnow() - timedelta(hours=40)
    db_session.add(WorkOrder(complaint_id=complaint.id, tenant_id=officer.tenant_id,
                             status="completed", sla_hours=24, created_at=created,
                             sla_deadline=created + timedelta(hours=24),
                             completed_at=utcnow()))
    db_session.commit()
    body = client.get(f"/admin/complaints/{complaint.id}", headers=auth).json()
    assert body["work_order"]["sla_state"] == "completed"


def test_the_filters_narrow_the_queue(client, db_session, officer, auth):
    _complaint(db_session, officer.tenant_id, category="ROADS", status="assigned")
    _complaint(db_session, officer.tenant_id, category="WATER", status="resolved")
    db_session.commit()

    assert len(client.get("/admin/complaints?category=WATER", headers=auth).json()["items"]) == 1
    assert len(client.get("/admin/complaints?status=resolved", headers=auth).json()["items"]) == 1
    assert len(client.get("/admin/complaints?category=ROADS&status=resolved",
                          headers=auth).json()["items"]) == 0


def test_the_search_matches_a_tracking_id_or_the_description(client, db_session, officer, auth):
    _complaint(db_session, officer.tenant_id, tracking_id="CIV-FINDME01",
               description="a blocked drain")
    db_session.commit()

    assert len(client.get("/admin/complaints?q=FINDME", headers=auth).json()["items"]) == 1
    assert len(client.get("/admin/complaints?q=blocked+drain", headers=auth).json()["items"]) == 1


def test_escalations_appear_on_the_detail(client, db_session, officer, auth):
    complaint = _complaint(db_session, officer.tenant_id)
    db_session.add(Escalation(complaint_id=complaint.id, from_level="ward",
                              to_level="block", reason="SLA breached"))
    db_session.commit()
    body = client.get(f"/admin/complaints/{complaint.id}", headers=auth).json()
    assert body["escalations"][0]["to_level"] == "block"


# ── what the officer must not see ───────────────────────────────────────────


def test_an_officer_sees_only_their_own_tenants_complaints(client, db_session, officer, auth):
    other = Tenant(name="Mysuru City Corporation", config={})
    db_session.add(other)
    db_session.flush()
    _complaint(db_session, officer.tenant_id, tracking_id="CIV-MINE0001")
    _complaint(db_session, other.id, tracking_id="CIV-THEIRS01")
    db_session.commit()

    body = client.get("/admin/complaints", headers=auth).json()
    assert [i["tracking_id"] for i in body["items"]] == ["CIV-MINE0001"]
    assert body["total"] == 1


def test_another_tenants_complaint_is_404_not_403(client, db_session, officer, auth):
    """403 would confirm the id is real somewhere in the system."""
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    theirs = _complaint(db_session, other.id)
    db_session.commit()

    assert client.get(f"/admin/complaints/{theirs.id}", headers=auth).status_code == 404


def test_an_officer_with_no_tenant_sees_nothing_rather_than_everything(
        client, db_session, officer, auth):
    """Fail closed, as route_node does: an unscoped query spans every municipality."""
    _complaint(db_session, officer.tenant_id)
    db_session.commit()
    officer.tenant_id = None
    db_session.commit()

    body = client.get("/admin/complaints", headers=auth).json()
    assert body["items"] == [] and body["total"] == 0


def test_the_page_size_is_capped(client, auth):
    """A tenant can hold a hundred thousand complaints."""
    assert client.get("/admin/complaints?size=5000", headers=auth).status_code == 422
    assert client.get("/admin/complaints?size=100", headers=auth).status_code == 200


def test_pagination_reports_the_total_and_the_page_count(client, db_session, officer, auth):
    for _ in range(7):
        _complaint(db_session, officer.tenant_id)
    db_session.commit()

    body = client.get("/admin/complaints?size=3&page=2", headers=auth).json()
    assert body["total"] == 7
    assert body["pages"] == 3
    assert body["page"] == 2
    assert len(body["items"]) == 3


def test_the_queue_needs_a_token_and_an_officer_role(client, db_session):
    assert client.get("/admin/complaints").status_code == 401

    citizen = User(email="c@example.com", name="C", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    token = create_access_token(user_id=citizen.id, role="citizen")
    assert client.get("/admin/complaints",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_the_list_does_not_query_once_per_complaint(client, db_session, officer, auth):
    """The N+1 guard. Each row needs its work order for the SLA state, so without
    selectinload a 100-row page is 101 queries."""
    for _ in range(12):
        complaint = _complaint(db_session, officer.tenant_id)
        db_session.add(WorkOrder(complaint_id=complaint.id, tenant_id=officer.tenant_id,
                                 status="assigned", sla_hours=24))
    db_session.commit()

    statements = []
    engine = db_session.get_bind()

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        body = client.get("/admin/complaints?size=12", headers=auth).json()
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(body["items"]) == 12
    assert len(statements) <= 5, (
        f"{len(statements)} selects for 12 rows — one per complaint means the "
        f"work order relationship is not being loaded eagerly:\n" + "\n".join(statements)
    )


def test_the_queue_carries_a_truncated_description(client, db_session, officer, auth):
    """An officer triaging a queue needs to see what the citizen actually said; a
    category alone does not tell them. Truncated, because a queue row is a row."""
    from app.schemas.admin import DESCRIPTION_PREVIEW_CHARS

    long_text = "The drain is blocked. " * 60
    db_session.add(Complaint(tracking_id="CIV-PREVIEW1", tenant_id=officer.tenant_id,
                             citizen_email="a@b.com", description=long_text,
                             category="WATER", status="assigned"))
    db_session.commit()

    row = next(r for r in client.get("/admin/complaints", headers=auth).json()["items"]
               if r["tracking_id"] == "CIV-PREVIEW1")
    preview = row["description_preview"]
    assert preview.startswith("The drain is blocked.")
    assert len(preview) <= DESCRIPTION_PREVIEW_CHARS + 1, "the ellipsis is the +1"
    assert preview.endswith("…")
    assert len(preview) < len(long_text)


def test_a_short_description_is_not_given_an_ellipsis(client, db_session, officer, auth):
    db_session.add(Complaint(tracking_id="CIV-PREVIEW2", tenant_id=officer.tenant_id,
                             citizen_email="a@b.com", description="A pothole.",
                             category="ROADS", status="assigned"))
    db_session.commit()

    row = next(r for r in client.get("/admin/complaints", headers=auth).json()["items"]
               if r["tracking_id"] == "CIV-PREVIEW2")
    assert row["description_preview"] == "A pothole."
