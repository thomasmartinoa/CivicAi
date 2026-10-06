"""The route dependencies, exercised through real routes.

Mounted on a throwaway router rather than on the real admin endpoints, so these
tests keep passing while the endpoints themselves are still being built, and so a
failure here points at the dependency rather than at whatever the route does.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import CurrentAdmin, CurrentOfficer, CurrentUser
from app.db.models.core import User
from app.db.session import get_db
from app.services.auth import create_access_token, hash_password


@pytest.fixture
def users(db_session):
    """One of each role, so every refusal has something concrete to refuse."""
    made = {}
    for role in ("citizen", "officer", "admin"):
        user = User(email=f"{role}@civicai.gov", name=role.title(), role=role,
                    password_hash=hash_password("pw"))
        db_session.add(user)
        made[role] = user
    db_session.commit()
    return made


@pytest.fixture
def client(db_session):
    app = FastAPI()

    @app.get("/any")
    def any_user(user: CurrentUser):
        return {"id": user.id, "role": user.role}

    @app.get("/officer")
    def officer_only(user: CurrentOfficer):
        return {"id": user.id}

    @app.get("/admin")
    def admin_only(user: CurrentAdmin):
        return {"id": user.id}

    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id=user.id, role=user.role)}"}


# ── 401: we do not know who you are ─────────────────────────────────────────


def test_no_token_is_401_not_403(client):
    """The distinction the frontend navigates on: 401 sends the user to login, 403
    shows a message. HTTPBearer's own default would return 403 here, which is why
    auto_error is off."""
    response = client.get("/officer")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_a_malformed_authorization_header_is_401_not_500(client):
    for header in ({"Authorization": "Bearer"},
                   {"Authorization": "Bearer "},
                   {"Authorization": "Basic abc"},
                   {"Authorization": "nonsense"},
                   {"Authorization": "Bearer a.b.c"}):
        assert client.get("/officer", headers=header).status_code == 401, header


def test_an_expired_token_is_401(client, users):
    from datetime import timedelta
    token = create_access_token(user_id=users["officer"].id, role="officer",
                                expires_delta=timedelta(seconds=-1))
    assert client.get("/officer", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_token_for_a_deleted_user_is_401(client, db_session, users):
    """A valid signature for somebody who no longer exists. Not 403 — there is
    nobody left to refuse."""
    headers = _auth(users["officer"])
    db_session.delete(users["officer"])
    db_session.commit()
    assert client.get("/officer", headers=headers).status_code == 401


def test_every_401_says_the_same_thing(client, users):
    """Which failure it was is information the caller has not earned: "expired"
    versus "bad signature" tells an attacker whether they guessed the secret."""
    from datetime import timedelta

    details = {
        client.get("/officer").json()["detail"],
        client.get("/officer", headers={"Authorization": "Bearer a.b.c"}).json()["detail"],
        client.get("/officer", headers={"Authorization": "Bearer " + create_access_token(
            user_id="ghost", role="officer")}).json()["detail"],
        client.get("/officer", headers={"Authorization": "Bearer " + create_access_token(
            user_id=users["officer"].id, role="officer",
            expires_delta=timedelta(seconds=-1))}).json()["detail"],
    }
    assert len(details) == 1, details


# ── 403: we know who you are, and no ────────────────────────────────────────


def test_a_citizen_token_on_an_officer_route_is_403(client, users):
    response = client.get("/officer", headers=_auth(users["citizen"]))
    assert response.status_code == 403
    assert "officer" in response.json()["detail"]


def test_an_officer_token_on_an_admin_route_is_403(client, users):
    assert client.get("/admin", headers=_auth(users["officer"])).status_code == 403


def test_a_citizen_can_still_use_a_plain_authenticated_route(client, users):
    response = client.get("/any", headers=_auth(users["citizen"]))
    assert response.status_code == 200
    assert response.json()["role"] == "citizen"


# ── the happy paths, and the role that is not taken on trust ────────────────


def test_an_officer_reaches_an_officer_route(client, users):
    assert client.get("/officer", headers=_auth(users["officer"])).status_code == 200


def test_an_admin_reaches_both(client, users):
    assert client.get("/officer", headers=_auth(users["admin"])).status_code == 200
    assert client.get("/admin", headers=_auth(users["admin"])).status_code == 200


def test_a_token_claiming_admin_for_a_citizen_account_is_refused(client, users):
    """The role is read from the database, not from the token. Otherwise anyone who
    could mint a token — or who held one from before a demotion — would keep the
    access it claims."""
    forged = create_access_token(user_id=users["citizen"].id, role="admin")
    response = client.get("/admin", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 403


def test_a_demotion_takes_effect_without_waiting_for_the_token_to_expire(
        client, db_session, users):
    headers = _auth(users["officer"])
    assert client.get("/officer", headers=headers).status_code == 200

    users["officer"].role = "citizen"
    db_session.commit()
    assert client.get("/officer", headers=headers).status_code == 403
