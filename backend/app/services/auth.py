"""Password verification and officer access tokens.

**bcrypt directly, not passlib.** passlib 1.7 reads `bcrypt.__about__.__version__`,
which bcrypt 4 removed, and it is unmaintained on Python 3.14. `services/seed.py`
has hashed with bcrypt directly since Phase 0 for the same reason, and this module
has to agree with it — `test_auth.py` checks that it does by verifying the seeded
admin's hash.

Two decisions about what the token holds and how it is read:

- **The algorithm is pinned on decode.** `jwt.decode(..., algorithms=[ALGORITHM])`
  rather than trusting the token's own header, because a decoder that honours the
  header accepts a token re-signed with `"alg": "none"` and an empty signature. That
  is the oldest JWT forgery there is, and it is one keyword argument away.
- **The token carries an opaque user id and a role, nothing else.** It sits in
  browser storage, travels in headers, and turns up in logs and bug reports; an email
  in there is a small data leak repeated everywhere the token goes. The role is
  included so a route can refuse early, but every request still loads the user, so a
  deleted or demoted account cannot keep acting on an old token's word.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
"""Pinned here rather than read from settings on decode. settings.algorithm exists
for symmetry with the rest of the config, and `_algorithms()` reconciles them, but
the decode list must never come from anything an attacker could influence."""


class InvalidToken(Exception):
    """The token was absent, malformed, expired, forged or signed with another key.

    One exception for every failure on purpose: the caller turns this into a 401 and
    must not leak which of those it was. "Expired" versus "bad signature" tells an
    attacker whether they guessed the secret.
    """


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    role: str
    expires_at: datetime


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    """Check a password. False, never an exception, on anything unusable.

    `User.password_hash` is nullable because a citizen has no password, and a hash
    can be truncated by a bad migration or edited by hand. Any of those is a failed
    login, not a 500 — and an empty password is always a refusal, since bcrypt would
    happily verify one against a hash of it.
    """
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        logger.warning("unusable password hash encountered during verification")
        return False


def _algorithms() -> list[str]:
    """The algorithms decode will accept.

    `settings.algorithm` is honoured so the config is not a lie, but the result is a
    fixed allow-list either way — the token's own header never contributes.
    """
    configured = (settings.algorithm or "").strip()
    return [configured] if configured else [ALGORITHM]


def create_access_token(*, user_id: str, role: str,
                        expires_delta: timedelta | None = None) -> str:
    issued = datetime.now(timezone.utc)
    expires = issued + (expires_delta if expires_delta is not None
                        else timedelta(minutes=settings.access_token_expire_minutes))
    return jwt.encode(
        {"sub": user_id, "role": role, "iat": issued, "exp": expires},
        settings.secret_key,
        algorithm=_algorithms()[0],
    )


def decode_token(token: str) -> TokenClaims:
    """Verify a token and return its claims, or raise InvalidToken."""
    if not token:
        raise InvalidToken("no token supplied")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=_algorithms())
    except JWTError as exc:
        # Deliberately not forwarding the reason: see InvalidToken's docstring.
        logger.info("rejected a token: %s", exc)
        raise InvalidToken("could not verify the token") from exc

    user_id = payload.get("sub")
    expires = payload.get("exp")
    if not user_id or expires is None:
        raise InvalidToken("the token is missing its subject or expiry")
    return TokenClaims(
        user_id=user_id,
        role=payload.get("role") or "citizen",
        expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
    )


CITIZEN_ROLE = "citizen_email"
"""The role on a token minted by the OTP flow.

Deliberately not "citizen": a `User` row with `role="citizen"` is a real account, and
these tokens stand for nothing more than "somebody proved they can read mail at this
address". Keeping the names apart means `get_current_user`, which looks a user up by
id, can never accidentally accept one.
"""

CITIZEN_TOKEN_MINUTES = 30


def create_citizen_token(email: str) -> str:
    """A short-lived token proving control of an email address.

    The subject is the address rather than a user id, because a citizen has no user
    row. Thirty minutes is long enough to read your complaints and short enough that
    a token left in a browser on a shared machine expires before the next person
    sits down.
    """
    return create_access_token(
        user_id=email.strip().lower(),
        role=CITIZEN_ROLE,
        expires_delta=timedelta(minutes=CITIZEN_TOKEN_MINUTES),
    )
