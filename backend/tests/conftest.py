import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models  # noqa: F401 — registers every model on Base.metadata
import app.db.session  # noqa: F401 — registers the PRAGMA foreign_keys=ON listener


@pytest.fixture
def db_session():
    """A fresh in-memory database per test. No file, no cleanup, no shared state."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
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
