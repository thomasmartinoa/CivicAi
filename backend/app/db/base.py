import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def gen_uuid() -> str:
    """UUID as a 36-char string. SQLite has no native UUID type."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    SQLite drops tzinfo on write, so values read back are naive. Anything doing
    arithmetic on a stored datetime must re-tag it with timezone.utc first.
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
