"""Who is calling, and whether they may.

Three dependencies, layered: `get_current_user` establishes identity,
`get_current_officer` and `get_current_admin` establish permission.

**401 and 403 mean different things and the difference is load-bearing.** 401 is
"I do not know who you are" and tells the frontend to send the user to the login
screen; 403 is "I know who you are and you may not do this" and tells it to show a
message instead. A layer that conflated them would make every permission error look
like an expired session, and the user would be bounced to a login that fixes nothing.

**The token's role is not trusted on its own.** Every request loads the user, so a
deleted account, or one demoted from officer to citizen, stops working immediately
rather than at the end of an eight-hour token's life. The role in the token exists so
the check can be cheap *and* then verified, not so it can be believed.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.models.core import User
from app.db.session import get_db
from app.services.auth import CITIZEN_ROLE, InvalidToken, decode_token

logger = logging.getLogger(__name__)

OFFICER_ROLES = frozenset({"officer", "admin"})
ADMIN_ROLES = frozenset({"admin"})

# auto_error=False so a missing header reaches our own code and becomes a 401 with a
# WWW-Authenticate challenge. HTTPBearer's own error is a 403, which would tell the
# frontend to show "not allowed" to someone who simply has not logged in.
_bearer = HTTPBearer(auto_error=False)


def _unauthenticated(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """The authenticated user, or 401.

    Every failure is the same 401 with the same detail: which of them it was —
    no header, malformed token, expired token, deleted user — is information the
    caller has not earned.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthenticated()
    try:
        claims = decode_token(credentials.credentials)
    except InvalidToken:
        raise _unauthenticated() from None

    user = db.query(User).filter(User.id == claims.user_id).one_or_none()
    if user is None:
        # A valid signature for a user who no longer exists. Not a 403: there is
        # nobody to refuse.
        logger.info("token presented for unknown user %s", claims.user_id)
        raise _unauthenticated()
    return user


def _require(user: User, roles: frozenset[str], what: str) -> User:
    if user.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This endpoint requires {what} access",
        )
    return user


def get_current_officer(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """An officer or an admin. The role comes from the database, not the token."""
    return _require(user, OFFICER_ROLES, "officer")


def get_current_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    return _require(user, ADMIN_ROLES, "admin")


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentOfficer = Annotated[User, Depends(get_current_officer)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]


def get_verified_citizen(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """The email address a citizen token proves control of.

    No database lookup, because there is no row to look up — the address *is* the
    identity. The role is checked explicitly so an officer's token cannot be used
    here either: an officer reading one citizen's complaints should go through the
    admin API, where it is logged against their account.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(credentials.credentials)
    except InvalidToken:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    if claims.role != CITIZEN_ROLE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims.user_id


VerifiedCitizen = Annotated[str, Depends(get_verified_citizen)]
