"""One-time codes for a citizen looking up their own complaints.

The whole value of this flow is that knowing an email address is not enough to read
what somebody reported, so most of this module is about the ways that could leak:

- **The code is never returned to the caller.** It goes by email. Returning it
  would make the flow decorative — anyone could ask for a code for any address and
  immediately use it.
- **Requesting a code looks identical for an address with complaints and one
  without.** Otherwise the endpoint enumerates which citizens have complained,
  which in a municipality is a list of who has complained about what.
- **A code is single-use, time-limited, and attempt-limited.** Six digits is a
  million guesses; without a ceiling on wrong attempts it is a few minutes of
  scripting.
- **Issuing is rate-limited per address**, so the endpoint cannot be used to flood
  somebody's inbox.

The code is stored hashed. Against an offline attacker that buys nothing — a million
candidates is instant — and the docstring on `CitizenOtp` says so. What it buys is
that a glance at the table, a backup, or a screenshot in a support thread does not
hand over a working code.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import utcnow
from app.db.models.core import CitizenOtp
from app.services.auth import hash_password, verify_password

logger = logging.getLogger(__name__)

CODE_LENGTH = 6
MAX_ATTEMPTS = 5
"""Wrong guesses before a code is dead. Five leaves room for a typo and still makes
guessing a six-digit code hopeless."""
MAX_ACTIVE_CODES = 3
RATE_LIMIT_WINDOW = timedelta(minutes=15)
"""Three codes per address per fifteen minutes. The limit protects the citizen's
inbox, not the server."""


class OtpRateLimited(RuntimeError):
    """Too many codes requested for one address recently."""


@dataclass(frozen=True)
class IssuedOtp:
    """The code and its row. The code is returned *to the caller inside this
    process* so it can be emailed — it must never reach an HTTP response."""

    code: str
    expires_at: object


def _normalise(email: str) -> str:
    return email.strip().lower()


def generate_code() -> str:
    """A cryptographically random six-digit code.

    `secrets`, not `random`: the latter is seeded predictably enough that codes
    could be guessed from a few observations.
    """
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def issue_code(session: Session, email: str) -> IssuedOtp:
    """Create a code for an address. Raises OtpRateLimited if asked too often.

    Any earlier unconsumed codes for the address are expired, so a citizen who
    requests a second code does not leave the first one working.
    """
    address = _normalise(email)
    recent = (session.query(CitizenOtp)
              .filter(CitizenOtp.email == address,
                      CitizenOtp.created_at >= utcnow() - RATE_LIMIT_WINDOW)
              .count())
    if recent >= MAX_ACTIVE_CODES:
        raise OtpRateLimited(f"too many codes requested for {address} recently")

    now = utcnow()
    superseded = (session.query(CitizenOtp)
                  .filter(CitizenOtp.email == address,
                          CitizenOtp.consumed_at.is_(None),
                          CitizenOtp.expires_at > now)
                  .all())
    for old in superseded:
        old.expires_at = now

    code = generate_code()
    row = CitizenOtp(
        email=address,
        code_hash=hash_password(code),
        expires_at=now + timedelta(minutes=settings.otp_expire_minutes),
    )
    session.add(row)
    session.commit()
    logger.info("issued an OTP for %s", address)
    return IssuedOtp(code=code, expires_at=row.expires_at)


def verify_code(session: Session, email: str, code: str) -> bool:
    """True if the code is live and correct, and consume it. False otherwise.

    One boolean, never a reason: "no code was issued for this address" and "that
    code is wrong" must be indistinguishable to the caller, or the endpoint reports
    which addresses have been asked about.
    """
    address = _normalise(email)
    now = utcnow()
    candidates = (session.query(CitizenOtp)
                  .filter(CitizenOtp.email == address,
                          CitizenOtp.consumed_at.is_(None),
                          CitizenOtp.expires_at > now,
                          CitizenOtp.attempts < MAX_ATTEMPTS)
                  .order_by(CitizenOtp.created_at.desc())
                  .all())

    for row in candidates:
        if verify_password(code, row.code_hash):
            row.consumed_at = now
            session.commit()
            return True

    # A wrong guess costs every live code an attempt, so a scripted walk through
    # the keyspace burns the budget rather than getting a fresh one each time.
    for row in candidates:
        row.attempts += 1
    session.commit()
    if candidates:
        logger.info("a wrong OTP was submitted for %s", address)
    return False


def complaints_for(session: Session, email: str) -> list:
    """Every complaint filed under this address, newest first.

    Called only after `verify_code` returned True. Scoped by the address and nothing
    else — a verified citizen sees their own complaints across tenants, because the
    address is the only identity they have.
    """
    from app.db.models.complaint import Complaint

    return (session.query(Complaint)
            .filter(Complaint.citizen_email == _normalise(email))
            .order_by(Complaint.created_at.desc())
            .all())
