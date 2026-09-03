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
