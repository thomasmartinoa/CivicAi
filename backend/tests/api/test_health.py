import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(monkeypatch, db_session):
    """`with TestClient(app) as c` runs lifespan startup/shutdown for real.

    The FIX 7 startup guard refuses to boot with the placeholder SECRET_KEY
    while ENVIRONMENT=production. There is no backend/.env in this repo, so
    that is exactly the ambient default here — tests configure a real
    secret the same way an actual deployment would, rather than disabling
    the guard.

    SessionLocal is patched where main.py looks it up, so the lifespan sweep
    runs against the fixture database.
    """
    import app.main as main_module
    monkeypatch.setattr(settings, "secret_key", "test-secret-key-not-the-placeholder")
    monkeypatch.setattr(main_module, "SessionLocal", lambda: db_session)
    with TestClient(app) as c:
        yield c


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_a_version(client):
    assert client.get("/health").json()["version"]


def test_uploads_are_mounted(client):
    """A missing file must 404 from the static mount, not 500 or route-miss."""
    assert client.get("/uploads/definitely-not-here.jpg").status_code == 404


def test_seed_is_refused_outside_development(client, monkeypatch):
    from app.api import system
    monkeypatch.setattr(system.settings, "environment", "production")
    assert client.post("/admin/seed").status_code == 404


def test_seed_defaults_to_refused_when_unconfigured():
    """The environment default must fail closed: an unconfigured deployment
    gets no unauthenticated seed endpoint."""
    from app.config import Settings
    assert Settings(_env_file=None).environment == "production"


def test_boot_refuses_placeholder_secret_in_production(monkeypatch):
    """FIX 7: an unconfigured production deployment must fail to boot loudly
    rather than silently sign JWTs with a public, well-known secret."""
    from app.main import _guard_against_placeholder_secret_in_production
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _guard_against_placeholder_secret_in_production()


def test_lifespan_sweep_resumes_submitted_complaints(db_session, monkeypatch):
    """The startup sweep queries the fixture database, not the real one."""
    import app.main as main_module
    from app.db.models.complaint import Complaint
    from app.db.models.core import Tenant
    from app.services.seed import seed_database

    # Create a submitted complaint in the fixture database
    seeded = seed_database(db_session)
    complaint = Complaint(
        tracking_id="CIV-SWEEP01",
        tenant_id=seeded["tenant_id"],
        citizen_email="a@b.com",
        description="Test complaint",
        status="submitted",
    )
    db_session.add(complaint)
    db_session.commit()

    monkeypatch.setattr(settings, "secret_key", "test-secret-key-not-the-placeholder")
    monkeypatch.setattr(main_module, "SessionLocal", lambda: db_session)

    # Capture schedule_complaint_run calls
    captured = []
    monkeypatch.setattr("app.services.execution.schedule_complaint_run",
                       lambda complaint_id: captured.append(complaint_id))

    # Boot the app
    with TestClient(app) as c:
        pass

    # Verify the sweep found and scheduled the complaint
    assert complaint.id in captured
