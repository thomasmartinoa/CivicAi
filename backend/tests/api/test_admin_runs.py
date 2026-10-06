"""The agent run and step timeline endpoints.

`agent_runs` has no tenant column, so the scoping here is a join rather than a filter
— which makes it the kind of thing that works until someone writes the obvious query.
Most of these tests are about that.
"""

from datetime import timedelta

import pytest

from app.db.base import utcnow
from app.db.models.ai import AgentRun, AgentStep
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant, User
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


def _complaint(db_session, tenant_id, tracking_id):
    row = Complaint(tracking_id=tracking_id, tenant_id=tenant_id,
                    citizen_email="a@b.com", description="a drain",
                    category="WATER", status="assigned")
    db_session.add(row)
    db_session.flush()
    return row


def _run(db_session, *, complaint=None, thread=None, status="completed", steps=0,
         started=None, step_status="completed"):
    started = started or utcnow()
    run = AgentRun(complaint_id=complaint.id if complaint else None,
                   thread_id=thread or (complaint.id if complaint else "chat:x:1"),
                   status=status, graph_version="2b.0", started_at=started,
                   finished_at=started + timedelta(seconds=1), duration_ms=1000)
    db_session.add(run)
    db_session.flush()
    for i in range(steps):
        db_session.add(AgentStep(run_id=run.id, seq=i, node=f"node{i}",
                                 status=step_status, duration_ms=10,
                                 input_summary=f"in{i}", output_summary=f"out{i}"))
    db_session.flush()
    return run


# ── scoping, which is the whole risk here ───────────────────────────────────


def test_a_pipeline_run_for_another_tenant_is_not_listed(db_session, client, officer, auth):
    """agent_runs has no tenant_id. Filtering the table directly — the obvious
    query — would return every tenant's runs."""
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    _run(db_session, complaint=_complaint(db_session, other.id, "CIV-THEIRS01"))
    _run(db_session, complaint=_complaint(db_session, officer.tenant_id, "CIV-MINE0001"))
    db_session.commit()

    items = client.get("/admin/runs", headers=auth).json()["items"]
    assert [i["tracking_id"] for i in items] == ["CIV-MINE0001"]


def test_another_officers_chat_is_not_listed(db_session, client, officer, auth):
    """A chat run has no complaint to join to, so it is scoped by the thread id
    chat_log writes. An officer sees their own conversations, not a colleague's."""
    colleague = User(email="other@gov", name="Other", role="officer",
                     tenant_id=officer.tenant_id, password_hash=hash_password("pw"))
    db_session.add(colleague)
    db_session.flush()
    _run(db_session, thread=f"chat:{colleague.id}:abc")
    _run(db_session, thread=f"chat:{officer.id}:def")
    db_session.commit()

    items = client.get("/admin/runs?kind=chat", headers=auth).json()["items"]
    assert [i["thread_id"] for i in items] == [f"chat:{officer.id}:def"]


def test_another_tenants_run_detail_is_404_not_403(db_session, client, officer, auth):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    run = _run(db_session, complaint=_complaint(db_session, other.id, "CIV-THEIRS02"))
    db_session.commit()

    assert client.get(f"/admin/runs/{run.id}", headers=auth).status_code == 404


def test_another_officers_chat_detail_is_404(db_session, client, officer, auth):
    run = _run(db_session, thread="chat:somebody-else:abc")
    db_session.commit()
    assert client.get(f"/admin/runs/{run.id}", headers=auth).status_code == 404


def test_the_endpoints_need_an_officer(client, db_session):
    assert client.get("/admin/runs").status_code == 401
    citizen = User(email="c@example.com", name="C", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    token = create_access_token(user_id=citizen.id, role="citizen")
    assert client.get("/admin/runs",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 403


# ── shape ───────────────────────────────────────────────────────────────────


def test_a_run_says_what_kind_it_is(db_session, client, officer, auth):
    """complaint_id IS NULL is the right storage decision and the wrong thing to make
    a frontend know."""
    _run(db_session, complaint=_complaint(db_session, officer.tenant_id, "CIV-PIPE0001"))
    _run(db_session, thread=f"chat:{officer.id}:abc")
    db_session.commit()

    kinds = {i["kind"]: i for i in client.get("/admin/runs", headers=auth).json()["items"]}
    assert set(kinds) == {"pipeline", "chat"}
    assert kinds["pipeline"]["tracking_id"] == "CIV-PIPE0001"
    assert kinds["chat"]["tracking_id"] is None


def test_runs_are_newest_first_and_carry_a_step_count(db_session, client, officer, auth):
    complaint = _complaint(db_session, officer.tenant_id, "CIV-ORDER001")
    _run(db_session, complaint=complaint, steps=2, started=utcnow() - timedelta(hours=2))
    _run(db_session, complaint=complaint, steps=5, started=utcnow())
    db_session.commit()

    items = client.get("/admin/runs", headers=auth).json()["items"]
    assert [i["step_count"] for i in items] == [5, 2]


def test_a_run_with_no_steps_counts_zero_not_null(db_session, client, officer, auth):
    """The outer join produces NULL, and a frontend rendering "null steps" looks
    broken."""
    _run(db_session, complaint=_complaint(db_session, officer.tenant_id, "CIV-NOSTEP01"))
    db_session.commit()
    assert client.get("/admin/runs", headers=auth).json()["items"][0]["step_count"] == 0


def test_the_detail_returns_steps_in_sequence(db_session, client, officer, auth):
    run = _run(db_session, complaint=_complaint(db_session, officer.tenant_id, "CIV-STEPS001"),
               steps=4)
    db_session.commit()

    body = client.get(f"/admin/runs/{run.id}", headers=auth).json()
    assert [s["seq"] for s in body["steps"]] == [0, 1, 2, 3]
    assert body["steps"][0]["input_summary"] == "in0"
    assert body["step_count"] == 4


def test_a_step_limit_surrender_survives_to_the_response(db_session, client, officer, auth):
    """Rendered as `completed`, an agent that ran out of steps looks like one that
    finished. The trace viewer can only show a surrender if the status reaches it."""
    run = _run(db_session, thread=f"chat:{officer.id}:abc", steps=1,
               step_status="step_limit")
    db_session.commit()

    body = client.get(f"/admin/runs/{run.id}", headers=auth).json()
    assert body["steps"][0]["status"] == "step_limit"


def test_runs_can_be_filtered_to_one_complaint(db_session, client, officer, auth):
    wanted = _complaint(db_session, officer.tenant_id, "CIV-WANTED01")
    other = _complaint(db_session, officer.tenant_id, "CIV-OTHER001")
    _run(db_session, complaint=wanted)
    _run(db_session, complaint=other)
    db_session.commit()

    items = client.get(f"/admin/runs?complaint_id={wanted.id}", headers=auth).json()["items"]
    assert [i["tracking_id"] for i in items] == ["CIV-WANTED01"]


def test_an_unknown_run_is_404(client, auth):
    assert client.get("/admin/runs/does-not-exist", headers=auth).status_code == 404


def test_the_page_size_is_capped(client, auth):
    assert client.get("/admin/runs?size=5000", headers=auth).status_code == 422
