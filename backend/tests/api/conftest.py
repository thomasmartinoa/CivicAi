import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.seed import seed_database


@pytest.fixture
def client(db_session, tmp_path, monkeypatch):
    """A TestClient whose get_db yields the test session, and whose background
    execution is captured rather than run — Task 3 wires the real thing.

    UPLOAD_ROOT is redirected into tmp_path (the same pattern Task 1's media
    tests use): several of these tests upload files, and the real UPLOAD_ROOT
    resolves inside the repository — writing there would litter the working
    tree with generated names a failing test could leave behind.

    secret_key is set to a real value the same way test_health.py's own
    `client` fixture does: `with TestClient(app) as c` runs lifespan startup
    for real, and main.py's `_guard_against_placeholder_secret_in_production`
    refuses to boot with the placeholder SECRET_KEY while
    ENVIRONMENT=production — the ambient default here, since there is no
    backend/.env in this repo.

    SessionLocal is patched where main.py looks it up, so the lifespan sweep
    runs against the fixture database.
    """
    from app.db.session import get_db
    from app.services import media as media_module
    import app.main as main_module

    monkeypatch.setattr(media_module, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(settings, "secret_key", "test-secret-key-not-the-placeholder")
    monkeypatch.setattr(main_module, "SessionLocal", lambda: db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    seed_database(db_session)
    captured: list[str] = []
    monkeypatch.setattr("app.api.complaints.schedule_complaint_run",
                        lambda complaint_id: captured.append(complaint_id))
    with TestClient(app) as c:
        c.captured_runs = captured
        c.upload_root = tmp_path
        yield c
    app.dependency_overrides.clear()
