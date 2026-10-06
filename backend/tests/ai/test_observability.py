"""Tracing, and the two things that must stay true about it.

It must be invisible when off — same results, no import of langsmith at module
scope — and it must never carry citizen identifiers, because the trace leaves the
building.
"""

import ast
from pathlib import Path

import pytest

from app.ai.observability import run_metadata, traced, tracing_enabled
from app.config import settings

APP = Path(__file__).resolve().parents[2] / "app"


@traced("double")
def _double(n):
    return n * 2


def test_traced_is_a_transparent_passthrough_when_tracing_is_off(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    assert _double(21) == 42


def test_traced_still_returns_the_same_result_with_tracing_on(monkeypatch):
    """Turning tracing on must not change what the function returns, only what is
    recorded about it."""
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-key")
    assert _double(21) == 42


def test_traced_survives_langsmith_being_absent(monkeypatch):
    """A missing optional dependency must not take the pipeline down."""
    import app.ai.observability as module

    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(module, "_load_traceable", lambda: None)
    module._CACHE.clear()

    @traced("boom")
    def f(x):
        return x + 1

    assert f(1) == 2


def test_a_traced_function_that_raises_still_raises(monkeypatch):
    monkeypatch.setattr(settings, "langsmith_tracing", False)

    @traced("raiser")
    def f():
        raise ValueError("kept")

    with pytest.raises(ValueError, match="kept"):
        f()


def test_tracing_is_off_without_a_key(monkeypatch):
    """Switching the flag on with no key would make every call try and fail."""
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "")
    assert tracing_enabled() is False


def test_no_module_imports_langsmith_at_module_scope():
    """It is optional, and importing it eagerly would slow every process that
    never traces — including the test suite."""
    offenders = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                # Only module-scope imports matter; a lazy one inside a function
                # has a parent that is not the Module node.
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if any(n.startswith("langsmith") for n in names) and node.col_offset == 0:
                    offenders.append(str(path.relative_to(APP)))
    assert not offenders, f"langsmith imported at module scope in: {offenders}"


# ── what leaves the building ────────────────────────────────────────────────


class _Complaint:
    id = "c-123"
    tracking_id = "CIV-SECRET1"
    tenant_id = "t-1"
    category = "ROADS"
    risk_level = "high"
    priority_score = 70
    pipeline_version = "2b.0"
    citizen_email = "someone@example.com"
    citizen_phone = "+91 99999 99999"
    citizen_name = "A Citizen"
    description = "there is a pothole outside my house at 14 Cross"
    address = "14 Cross, Bengaluru"


def test_run_metadata_carries_no_citizen_identifiers():
    """This dict goes to a third party."""
    metadata = run_metadata(_Complaint())
    flat = " ".join(f"{k}={v}" for k, v in metadata.items())
    for leaked in ("someone@example.com", "99999", "A Citizen", "pothole", "14 Cross"):
        assert leaked not in flat, f"{leaked!r} must not be in the trace metadata"


def test_run_metadata_does_not_carry_the_tracking_id():
    """The tracking id is the only credential for reading a complaint — it is
    deliberately unguessable (see api/complaints.py). Sending it to a trace
    backend would put a credential in a third party's logs."""
    assert "CIV-SECRET1" not in str(run_metadata(_Complaint()))


def test_run_metadata_carries_what_makes_langsmith_filterable():
    metadata = run_metadata(_Complaint())
    assert metadata["complaint_id"] == "c-123"
    assert metadata["category"] == "ROADS"
    assert metadata["risk_level"] == "high"
    assert metadata["pipeline_version"] == "2b.0"


def test_run_metadata_handles_a_complaint_that_has_not_been_classified_yet():
    class Fresh(_Complaint):
        category = None
        risk_level = None
        pipeline_version = None

    metadata = run_metadata(Fresh())
    assert metadata["category"] is None
    assert "complaint_id" in metadata
