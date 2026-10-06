"""The citizen email and OTP flow.

A citizen has no account; the only thing tying them to a complaint is the address
they filed it under. So the question every test here asks is: does knowing an email
address get you anything it should not?
"""

from datetime import timedelta

import pytest

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import CitizenOtp
from app.services.otp import MAX_ACTIVE_CODES, MAX_ATTEMPTS, issue_code


@pytest.fixture
def sent(monkeypatch):
    """Capture the emails instead of sending them, and expose the code to the test —
    which is the only place it is ever allowed to be visible."""
    captured = []
    monkeypatch.setattr("app.services.notify._send_email",
                        lambda recipient, subject, body: captured.append(
                            {"to": recipient, "subject": subject, "body": body}))
    return captured


@pytest.fixture
def complainant(db_session, client):
    row = Complaint(tracking_id="CIV-CITIZEN1", citizen_email="citizen@example.com",
                    description="a pothole outside my house", category="ROADS",
                    status="assigned")
    db_session.add(row)
    db_session.commit()
    return row


def _code_from(email_body: str) -> str:
    import re
    return re.search(r"\b(\d{6})\b", email_body).group(1)


# ── requesting a code ───────────────────────────────────────────────────────


def test_a_code_is_emailed_and_never_returned(client, complainant, sent):
    """Returning it would make the whole flow decorative."""
    response = client.post("/complaints/verify-email",
                           json={"email": "citizen@example.com"})
    assert response.status_code == 200
    assert sent, "a code should have been emailed"

    code = _code_from(sent[0]["body"])
    assert code not in response.text
    assert len(code) == 6


def test_requesting_a_code_for_an_unknown_address_looks_identical(client, complainant, sent):
    """Otherwise this endpoint answers "has this person complained?", which for a
    municipality is a question about somebody's dealings with the state."""
    known = client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    unknown = client.post("/complaints/verify-email", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_nothing_is_emailed_to_an_address_with_no_complaints(client, sent):
    client.post("/complaints/verify-email", json={"email": "nobody@example.com"})
    assert sent == []


def test_the_address_is_matched_case_insensitively(client, complainant, sent):
    client.post("/complaints/verify-email", json={"email": "Citizen@Example.COM"})
    assert sent, "a capitalised address is the same address"


def test_repeated_requests_are_rate_limited_and_still_answer_identically(
        client, complainant, sent):
    """The limit protects the citizen's inbox. A caller who hits it must not be able
    to tell, or the limit itself becomes a signal."""
    responses = [client.post("/complaints/verify-email",
                             json={"email": "citizen@example.com"})
                 for _ in range(MAX_ACTIVE_CODES + 2)]

    assert {r.status_code for r in responses} == {200}
    assert len({r.text for r in responses}) == 1
    assert len(sent) == MAX_ACTIVE_CODES, "the extra requests sent nothing"


def test_a_dead_mail_relay_does_not_change_the_answer(client, complainant, monkeypatch):
    """The code is already issued and usable. A broken SMTP relay is an operational
    problem, not something to report to the caller."""
    def explode(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("app.services.notify._send_email", explode)
    assert client.post("/complaints/verify-email",
                       json={"email": "citizen@example.com"}).status_code == 200


# ── using a code ────────────────────────────────────────────────────────────


def test_a_correct_code_returns_that_addresss_complaints(client, complainant, sent):
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    code = _code_from(sent[0]["body"])

    response = client.post("/complaints/verify-otp",
                           json={"email": "citizen@example.com", "code": code})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "citizen@example.com"
    assert [c["tracking_id"] for c in body["complaints"]] == ["CIV-CITIZEN1"]


def test_a_code_returns_only_that_addresss_complaints(client, db_session, complainant, sent):
    db_session.add(Complaint(tracking_id="CIV-SOMEONE1", citizen_email="other@example.com",
                             description="not yours", status="assigned"))
    db_session.commit()

    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    code = _code_from(sent[0]["body"])
    body = client.post("/complaints/verify-otp",
                       json={"email": "citizen@example.com", "code": code}).json()
    assert [c["tracking_id"] for c in body["complaints"]] == ["CIV-CITIZEN1"]


def test_a_used_code_cannot_be_replayed(client, complainant, sent):
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    code = _code_from(sent[0]["body"])
    payload = {"email": "citizen@example.com", "code": code}

    assert client.post("/complaints/verify-otp", json=payload).status_code == 200
    assert client.post("/complaints/verify-otp", json=payload).status_code == 401


def test_a_code_expires(client, db_session, complainant, sent):
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    code = _code_from(sent[0]["body"])

    row = db_session.query(CitizenOtp).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()

    assert client.post("/complaints/verify-otp",
                       json={"email": "citizen@example.com", "code": code}).status_code == 401


def test_a_wrong_code_does_not_reveal_whether_the_address_had_one(
        client, complainant, sent):
    """Both answers are the same 401 with the same detail."""
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})

    had_one = client.post("/complaints/verify-otp",
                          json={"email": "citizen@example.com", "code": "000000"})
    had_none = client.post("/complaints/verify-otp",
                           json={"email": "nobody@example.com", "code": "000000"})
    assert had_one.status_code == had_none.status_code == 401
    assert had_one.json()["detail"] == had_none.json()["detail"]


def test_guessing_is_capped(client, db_session, complainant, sent):
    """Six digits is a million guesses, which is minutes of scripting without a
    ceiling."""
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    code = _code_from(sent[0]["body"])

    for _ in range(MAX_ATTEMPTS):
        client.post("/complaints/verify-otp",
                    json={"email": "citizen@example.com", "code": "000000"})

    assert client.post("/complaints/verify-otp",
                       json={"email": "citizen@example.com", "code": code}).status_code == 401, (
        "the correct code must be dead once the attempt budget is spent"
    )


def test_requesting_a_second_code_retires_the_first(client, complainant, sent):
    """Otherwise a citizen who requests again because the first did not arrive
    leaves two live codes behind."""
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    first = _code_from(sent[0]["body"])
    client.post("/complaints/verify-email", json={"email": "citizen@example.com"})
    second = _code_from(sent[1]["body"])

    assert client.post("/complaints/verify-otp",
                       json={"email": "citizen@example.com", "code": first}).status_code == 401
    assert client.post("/complaints/verify-otp",
                       json={"email": "citizen@example.com", "code": second}).status_code == 200


# ── storage ─────────────────────────────────────────────────────────────────


def test_the_code_is_not_stored_in_the_clear(db_session, complainant):
    """A glance at this table, a backup or a screenshot in a support thread must not
    hand over a working code."""
    issued = issue_code(db_session, "citizen@example.com")
    row = db_session.query(CitizenOtp).one()
    assert issued.code not in row.code_hash
    assert row.code_hash.startswith("$2b$")


def test_codes_are_random_rather_than_sequential(db_session, complainant):
    """secrets, not random: a predictably seeded generator lets codes be guessed
    from a few observations."""
    from app.services.otp import generate_code

    codes = {generate_code() for _ in range(200)}
    assert len(codes) > 150, "a six-digit space should barely collide over 200 draws"
    assert all(len(c) == 6 and c.isdigit() for c in codes)
