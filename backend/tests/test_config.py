from app.config import Settings
from app.constants import Category, RiskLevel, CATEGORY_DEPARTMENT


def test_settings_have_sqlite_default():
    s = Settings(_env_file=None)
    assert s.database_url.startswith("sqlite")


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    s = Settings(_env_file=None)
    assert s.gemini_api_key == "test-key-123"


def test_there_are_twelve_categories():
    assert len(Category) == 12
    assert Category.ROADS == "ROADS"


def test_risk_levels_are_ordered_bands():
    assert [r.value for r in RiskLevel] == ["critical", "high", "medium", "low"]


def test_every_category_maps_to_a_department():
    """v1 Bug 3: two categories mapped to departments that did not exist."""
    for category in Category:
        assert category in CATEGORY_DEPARTMENT, f"{category} has no department"
        assert CATEGORY_DEPARTMENT[category], f"{category} maps to an empty name"
