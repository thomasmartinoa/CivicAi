from pathlib import Path

from app.config import Settings
from app.constants import Category, RiskLevel, CATEGORY_DEPARTMENT

# Fields legitimately not documented in .env.example (e.g. because they must
# never be given a real-looking placeholder). Keep this empty unless there is
# a genuine reason — the point of the test below is that new settings fields
# get documented, not that they get quietly exempted.
_ENV_EXAMPLE_EXEMPT: set[str] = set()


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


def test_every_settings_field_is_documented_in_env_example():
    """.env.example is the operator-facing list of what can be configured.
    A field added to Settings but never added there is invisible until
    someone reads the source — this guards against exactly that drift."""
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    content = env_example.read_text()

    for name in Settings.model_fields:
        if name in _ENV_EXAMPLE_EXEMPT:
            continue
        key = name.upper()
        assert f"{key}=" in content, f"{key} is a Settings field but missing from .env.example"
