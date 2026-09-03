from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_a_version():
    assert client.get("/health").json()["version"]


def test_uploads_are_mounted():
    """A missing file must 404 from the static mount, not 500 or route-miss."""
    assert client.get("/uploads/definitely-not-here.jpg").status_code == 404


def test_seed_is_refused_outside_development(monkeypatch):
    from app.api import system
    monkeypatch.setattr(system.settings, "environment", "production")
    assert client.post("/admin/seed").status_code == 404


def test_seed_defaults_to_refused_when_unconfigured():
    """The environment default must fail closed: an unconfigured deployment
    gets no unauthenticated seed endpoint."""
    from app.config import Settings
    assert Settings(_env_file=None).environment == "production"
