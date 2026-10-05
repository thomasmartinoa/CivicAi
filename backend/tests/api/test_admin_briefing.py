"""The briefing and the email-draft flow.

No model is called: `_email_draft_chain` is replaced with a fake, exactly as the
service's own tests do, so the suite stays offline.
"""

import pytest

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant, User
from app.db.models.workflow import DailyBriefing
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


@pytest.fixture
def complaint(db_session, officer):
    row = Complaint(tracking_id="CIV-DRAFT001", tenant_id=officer.tenant_id,
                    citizen_email="a@b.com", description="Huge pothole outside the school",
                    category="ROADS", risk_level="high", status="assigned")
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def fake_chain(monkeypatch):
    """A draft chain that returns fixed prose, or raises if asked to."""
    from langchain_core.runnables import RunnableLambda

    import app.api.admin as admin_module
    from app.ai.schemas import EmailDraft

    state = {"raise": None}

    def factory():
        def run(_payload):
            if state["raise"]:
                raise state["raise"]
            return EmailDraft(subject="Pothole at the school gate — action required",
                              body="Under the Roads SOP [1] this is Public Works' job.",
                              citations=["sop_roads.md › Roads SOP › Ownership"])
        return RunnableLambda(run)

    monkeypatch.setattr(admin_module, "_email_draft_chain", factory)
    monkeypatch.setattr(admin_module, "_email_draft_retriever", lambda: None)
    return state


# ── the briefing ────────────────────────────────────────────────────────────


def test_the_briefing_response_says_when_it_is_fallback_text(client, db_session,
                                                             officer, auth):
    """v1 served the template for the life of the project because nothing surfaced
    that the model had never run. The flag has to reach the screen."""
    db_session.add(DailyBriefing(tenant_id=officer.tenant_id, brief_date=utcnow(),
                                 narrative="4 new complaints were logged.",
                                 new_complaints=4, is_fallback=True))
    db_session.commit()

    body = client.get("/admin/briefing", headers=auth).json()
    assert body["is_fallback"] is True
    assert body["new_complaints"] == 4


def test_the_most_recent_briefing_wins(client, db_session, officer, auth):
    from datetime import timedelta

    db_session.add(DailyBriefing(tenant_id=officer.tenant_id,
                                 brief_date=utcnow() - timedelta(days=1),
                                 narrative="yesterday", is_fallback=False))
    db_session.add(DailyBriefing(tenant_id=officer.tenant_id, brief_date=utcnow(),
                                 narrative="today", is_fallback=False))
    db_session.commit()

    assert client.get("/admin/briefing", headers=auth).json()["narrative"] == "today"


def test_no_briefing_yet_is_404_not_an_empty_narrative(client, auth):
    """A blank briefing cannot be told from a quiet day."""
    assert client.get("/admin/briefing", headers=auth).status_code == 404


def test_another_tenants_briefing_is_not_served(client, db_session, officer, auth):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    db_session.add(DailyBriefing(tenant_id=other.id, brief_date=utcnow(),
                                 narrative="not yours", is_fallback=False))
    db_session.commit()

    assert client.get("/admin/briefing", headers=auth).status_code == 404


def test_the_briefing_needs_an_officer(client, db_session):
    assert client.get("/admin/briefing").status_code == 401
    citizen = User(email="c@example.com", name="C", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    token = create_access_token(user_id=citizen.id, role="citizen")
    assert client.get("/admin/briefing",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 403


# ── generating a draft ──────────────────────────────────────────────────────


def test_a_draft_is_generated_and_stored_unapproved(client, db_session, complaint,
                                                    auth, fake_chain):
    response = client.post(f"/admin/complaints/{complaint.id}/email-draft", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["department"] == "Public Works Department"
    assert "Public Works" in body["draft"]
    assert body["approved"] is False, "generating is not approving"

    db_session.expire_all()
    assert db_session.query(Complaint).filter_by(id=complaint.id).one().email_approved is False


def test_a_model_outage_while_drafting_is_503_not_500(client, complaint, auth, fake_chain):
    """A 500 tells the officer the system is broken when it is only busy."""
    fake_chain["raise"] = RuntimeError("429 RESOURCE_EXHAUSTED")
    response = client.post(f"/admin/complaints/{complaint.id}/email-draft", headers=auth)
    assert response.status_code == 503
    assert "try again" in response.json()["detail"].lower()


def test_an_unclassified_complaint_cannot_be_drafted(client, db_session, officer,
                                                     auth, fake_chain):
    """There is no department to write to, which is a state problem rather than a
    bad request."""
    row = Complaint(tracking_id="CIV-NOCAT001", tenant_id=officer.tenant_id,
                    citizen_email="a@b.com", description="something is wrong somewhere",
                    status="submitted")
    db_session.add(row)
    db_session.commit()

    response = client.post(f"/admin/complaints/{row.id}/email-draft", headers=auth)
    assert response.status_code == 409
    assert "classified" in response.json()["detail"]


def test_another_tenants_complaint_cannot_be_drafted(client, db_session, auth, fake_chain):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    theirs = Complaint(tracking_id="CIV-THEIRS01", tenant_id=other.id,
                       citizen_email="a@b.com", description="x", category="ROADS")
    db_session.add(theirs)
    db_session.commit()

    assert client.post(f"/admin/complaints/{theirs.id}/email-draft",
                       headers=auth).status_code == 404


# ── approving ───────────────────────────────────────────────────────────────


def test_approving_marks_the_draft_approved(client, db_session, complaint, auth, fake_chain):
    client.post(f"/admin/complaints/{complaint.id}/email-draft", headers=auth)
    response = client.post(f"/admin/complaints/{complaint.id}/email-draft/approve",
                           headers=auth)
    assert response.status_code == 200
    assert response.json()["approved"] is True

    db_session.expire_all()
    assert db_session.query(Complaint).filter_by(id=complaint.id).one().email_approved is True


def test_approving_twice_is_idempotent(client, complaint, auth, fake_chain):
    """A double click must not be an error."""
    client.post(f"/admin/complaints/{complaint.id}/email-draft", headers=auth)
    first = client.post(f"/admin/complaints/{complaint.id}/email-draft/approve", headers=auth)
    second = client.post(f"/admin/complaints/{complaint.id}/email-draft/approve", headers=auth)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_approving_an_empty_draft_is_refused(client, complaint, auth):
    """It would set a flag saying a human signed off on text that does not exist."""
    response = client.post(f"/admin/complaints/{complaint.id}/email-draft/approve",
                           headers=auth)
    assert response.status_code == 409
    assert "no draft" in response.json()["detail"].lower()


def test_regenerating_over_an_approved_draft_leaves_it_alone(client, db_session, complaint,
                                                             auth, fake_chain):
    """The service refuses to overwrite approved wording; the endpoint must not work
    around it, because the officer's name is on what they approved."""
    client.post(f"/admin/complaints/{complaint.id}/email-draft", headers=auth)
    client.post(f"/admin/complaints/{complaint.id}/email-draft/approve", headers=auth)
    db_session.expire_all()
    approved_text = db_session.query(Complaint).filter_by(id=complaint.id).one().email_draft

    client.post(f"/admin/complaints/{complaint.id}/email-draft", headers=auth)
    db_session.expire_all()
    stored = db_session.query(Complaint).filter_by(id=complaint.id).one()
    assert stored.email_draft == approved_text
    assert stored.email_approved is True


def test_approving_needs_an_officer(client, complaint):
    assert client.post(
        f"/admin/complaints/{complaint.id}/email-draft/approve").status_code == 401
