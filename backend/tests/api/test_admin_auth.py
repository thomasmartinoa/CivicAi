"""Officer login.

The security property worth testing is not that the right password works — it is
that a wrong one tells you nothing you did not already know.
"""

import pytest

from app.db.models.core import User
from app.services.auth import hash_password


@pytest.fixture
def officer(db_session, client):
    """The seeded tenant already has officers; this one has a known password."""
    user = User(email="officer@civicai.gov", name="Test Officer", role="officer",
                tenant_id=db_session.query(User).first().tenant_id,
                password_hash=hash_password("officer-pw"))
    db_session.add(user)
    db_session.commit()
    return user


def test_an_officer_can_log_in_and_the_token_works(client, officer):
    response = client.post("/admin/login",
                           json={"email": "officer@civicai.gov", "password": "officer-pw"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "officer"
    assert body["user"]["email"] == "officer@civicai.gov"

    me = client.get("/admin/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == officer.id


def test_an_unknown_email_and_a_wrong_password_are_indistinguishable(client, officer):
    """Otherwise this endpoint enumerates the municipality's staff."""
    unknown = client.post("/admin/login",
                          json={"email": "nobody@civicai.gov", "password": "whatever"})
    wrong = client.post("/admin/login",
                        json={"email": "officer@civicai.gov", "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_the_login_response_carries_no_password_hash(client, officer):
    body = client.post("/admin/login",
                       json={"email": "officer@civicai.gov", "password": "officer-pw"}).json()
    assert "password_hash" not in str(body)


def test_the_email_is_matched_case_insensitively(client, officer):
    """People type their own address with a capital letter."""
    response = client.post("/admin/login",
                           json={"email": "Officer@CivicAI.gov", "password": "officer-pw"})
    assert response.status_code == 200


def test_a_citizen_with_a_password_cannot_log_in_here(client, db_session):
    citizen = User(email="citizen@example.com", name="A Citizen", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    response = client.post("/admin/login",
                           json={"email": "citizen@example.com", "password": "pw"})
    assert response.status_code == 403


def test_a_user_with_no_password_cannot_log_in(client, db_session):
    """A citizen row has password_hash NULL. Verifying against it must refuse rather
    than crash."""
    user = User(email="nopassword@civicai.gov", name="No Password",
                role="officer", password_hash=None)
    db_session.add(user)
    db_session.commit()
    response = client.post("/admin/login",
                           json={"email": "nopassword@civicai.gov", "password": ""})
    assert response.status_code == 401


def test_me_requires_a_token(client):
    assert client.get("/admin/me").status_code == 401
