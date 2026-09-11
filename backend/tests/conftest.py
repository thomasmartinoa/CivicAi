import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
import app.db.models  # noqa: F401 — registers every model on Base.metadata
import app.db.session  # noqa: F401 — registers the PRAGMA foreign_keys=ON listener


@pytest.fixture
def db_session():
    """A fresh in-memory database per test. No file, no cleanup, no shared state.

    StaticPool keeps every checkout on the same single connection. Without it
    SQLAlchemy's default pooling for `sqlite://` hands out a new connection
    per thread — and a new connection to `:memory:` is a new, empty database —
    which surfaces the moment a test drives this session through a TestClient,
    whose ASGI app runs in its own thread: the app would see "no such table"
    against a database the fixture never touched.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch):
    """bcrypt is deliberately slow; seed_database hashes 11 passwords.

    Tests care that a password is hashed, never how expensive the hash is, so
    drop the cost factor to the minimum. Production hashing is untouched.
    """
    import bcrypt

    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=4: real_gensalt(4))
