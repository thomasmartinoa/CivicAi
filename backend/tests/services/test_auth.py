"""Password verification and officer tokens.

Almost every test here is a negative one. The happy path is three lines of library
calls; what matters is what this refuses — a forged algorithm, an expired token, a
token signed with a different secret, a password checked against a citizen's null
hash.
"""

import base64
import json
from datetime import timedelta

import pytest
from jose import jwt

from app.config import settings
from app.services.auth import (
    ALGORITHM, InvalidToken, create_access_token, decode_token, hash_password,
    verify_password,
)


# ── passwords ───────────────────────────────────────────────────────────────


def test_a_hashed_password_verifies_and_a_wrong_one_does_not():
    hashed = hash_password("officer123")
    assert verify_password("officer123", hashed) is True
    assert verify_password("officer124", hashed) is False


def test_the_same_password_hashes_differently_each_time():
    """bcrypt salts, so two hashes of one password must differ — otherwise equal
    hashes in the table would tell an attacker two people share a password."""
    assert hash_password("same") != hash_password("same")


def test_verifying_against_a_missing_hash_is_false_not_an_exception():
    """User.password_hash is nullable: a citizen row has none. Logging in as one
    must be a refusal, not a 500."""
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False


def test_verifying_against_a_corrupt_hash_is_false_not_an_exception():
    """A truncated or hand-edited hash in the database must not crash login."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_an_empty_password_never_verifies():
    assert verify_password("", hash_password("officer123")) is False


def test_the_seeded_admin_password_verifies_against_the_seeded_hash(db_session):
    """The seed hashes with bcrypt directly because passlib does not work on
    Python 3.14. This proves the two halves agree."""
    from app.db.models.core import User
    from app.services.seed import seed_database

    seed_database(db_session)
    admin = db_session.query(User).filter_by(email="admin@civicai.gov").one()
    assert verify_password(settings.seed_admin_password, admin.password_hash) is True
    assert verify_password("wrong", admin.password_hash) is False


# ── tokens ──────────────────────────────────────────────────────────────────


def test_a_token_round_trips_its_claims():
    token = create_access_token(user_id="u-1", role="officer")
    claims = decode_token(token)
    assert claims.user_id == "u-1"
    assert claims.role == "officer"
    assert claims.expires_at is not None


def test_a_token_signed_with_another_secret_is_refused(monkeypatch):
    token = create_access_token(user_id="u-1", role="officer")
    monkeypatch.setattr(settings, "secret_key", "a-different-secret-entirely")
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_an_expired_token_is_refused():
    token = create_access_token(user_id="u-1", role="officer",
                                expires_delta=timedelta(seconds=-1))
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_a_token_with_alg_none_is_refused():
    """The classic JWT forgery: re-sign the payload with "alg": "none" and an empty
    signature. A decoder that honours the header's algorithm accepts it."""
    forged = jwt.encode({"sub": "u-1", "role": "admin"}, key="", algorithm="HS256")
    header, payload, _ = forged.split(".")
    none_header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(InvalidToken):
        decode_token(f"{none_header}.{payload}.")


def test_a_token_signed_with_a_different_algorithm_is_refused():
    """Pinning the algorithm list is what makes the previous test hold in general."""
    other = jwt.encode({"sub": "u-1", "role": "admin",
                        "exp": 9999999999}, settings.secret_key, algorithm="HS512")
    assert ALGORITHM != "HS512"
    with pytest.raises(InvalidToken):
        decode_token(other)


def test_rubbish_is_refused_rather_than_crashing():
    for value in ("", "not.a.token", "a.b.c", "....", "Bearer something"):
        with pytest.raises(InvalidToken):
            decode_token(value)


def test_a_token_without_a_subject_is_refused():
    token = jwt.encode({"role": "admin", "exp": 9999999999},
                       settings.secret_key, algorithm=ALGORITHM)
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_a_token_carries_no_email_or_name():
    """It lives in browser storage and turns up in logs and bug reports, so it holds
    an opaque id and a role and nothing a person could be identified by."""
    token = create_access_token(user_id="u-1", role="officer")
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert set(payload) <= {"sub", "role", "exp", "iat"}
    assert payload["sub"] == "u-1"


def test_the_expiry_follows_the_configured_window(monkeypatch):
    monkeypatch.setattr(settings, "access_token_expire_minutes", 5)
    claims = decode_token(create_access_token(user_id="u-1", role="officer"))
    from datetime import datetime, timezone
    remaining = (claims.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 240 < remaining <= 300
