import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(monkeypatch):
    """`with TestClient(app) as c` runs lifespan startup/shutdown for real.

    The FIX 7 startup guard refuses to boot with the placeholder SECRET_KEY
    while ENVIRONMENT=production. There is no backend/.env in this repo, so
    that is exactly the ambient default here — tests configure a real
    secret the same way an actual deployment would, rather than disabling
    the guard.
    """
    monkeypatch.setattr(settings, "secret_key", "test-secret-key-not-the-placeholder")
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
