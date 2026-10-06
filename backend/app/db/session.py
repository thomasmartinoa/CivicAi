import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# check_same_thread=False is required because FastAPI serves requests from a
# thread pool and SQLite otherwise refuses cross-thread connection reuse.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ships with foreign key enforcement OFF, per connection.

    Without this every ForeignKey in the schema is decorative: a child row
    referencing a nonexistent parent inserts cleanly. Registered on Engine
    rather than on our engine so test fixtures inherit it.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
