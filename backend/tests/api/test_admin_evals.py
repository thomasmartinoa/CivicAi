"""The eval dashboard endpoint.

The interesting assertion is the staleness flag. A baseline measured under a
different validator describes a different population reaching `classify`, so a
regression against it may be a population change rather than a model change — and a
dashboard that does not say so is worse than one with no baseline at all.
"""

import json

import pytest

from app.db.base import utcnow
from app.db.models.core import User
from app.db.models.evaluation import EvalResult, EvalRun
from app.services.auth import create_access_token, hash_password


@pytest.fixture
def officer(db_session, client):
    user = db_session.query(User).filter(User.role.in_(("officer", "admin"))).first()
    user.password_hash = hash_password("pw")
    db_session.commit()
    return user


@pytest.fixture
def auth(officer):
    return {"Authorization": f"Bearer {create_access_token(user_id=officer.id, role=officer.role)}"}


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    """Point the endpoint at a temporary baseline so these tests neither read nor
    depend on the committed one."""
    import app.api.admin as admin_module

    path = tmp_path / "core.json"
    monkeypatch.setattr(admin_module, "BASELINE_PATH", path)
    return path


def _run(db_session, *, label, macro_f1=None, started=None, suite="core"):
    from datetime import timedelta

    run = EvalRun(suite=suite, dataset_name="golden_v1", dataset_hash="abc",
                  git_sha="deadbeef", config_label=label,
                  started_at=started or utcnow(),
                  finished_at=(started or utcnow()) + timedelta(seconds=1))
    db_session.add(run)
    db_session.flush()
    if macro_f1 is not None:
        db_session.add(EvalResult(eval_run_id=run.id, metric="macro_f1",
                                  value=macro_f1, detail_json={"n": 70}))
    db_session.flush()
    return run


# ── the staleness flag ──────────────────────────────────────────────────────


def test_a_baseline_from_a_different_validator_is_flagged_stale(client, auth, baseline):
    """Promoting validate v2 changed which complaints reach classify, so the 0.93
    measured under v1 is not a figure the gate can compare against honestly."""
    baseline.write_text(json.dumps({"macro_f1": 0.93, "validate_version": "v1"}))

    body = client.get("/admin/evals", headers=auth).json()
    assert body["baseline"]["stale"] is True
    assert body["baseline"]["macro_f1"] == 0.93


def test_a_baseline_from_the_current_validator_is_not_stale(client, auth, baseline, monkeypatch):
    from app.ai.prompts import LATEST

    monkeypatch.setitem(LATEST, "validate", "v2")
    baseline.write_text(json.dumps({"macro_f1": 0.95, "validate_version": "v2"}))

    assert client.get("/admin/evals", headers=auth).json()["baseline"]["stale"] is False


def test_staleness_is_derived_rather_than_trusted_from_the_file(client, auth, baseline,
                                                                monkeypatch):
    """A stored flag drifts the moment someone promotes a prompt and forgets to edit
    the json. Deriving it means it cannot."""
    from app.ai.prompts import LATEST

    monkeypatch.setitem(LATEST, "validate", "v9")
    baseline.write_text(json.dumps({"macro_f1": 0.93, "validate_version": "v1",
                                    "stale": False}))

    assert client.get("/admin/evals", headers=auth).json()["baseline"]["stale"] is True


def test_a_baseline_with_no_recorded_validator_is_not_claimed_stale(client, auth, baseline):
    """Unknown is not the same as mismatched, and guessing would cry wolf."""
    baseline.write_text(json.dumps({"macro_f1": 0.93}))
    assert client.get("/admin/evals", headers=auth).json()["baseline"]["stale"] is False


def test_a_missing_baseline_is_null_rather_than_an_error(client, auth, baseline):
    body = client.get("/admin/evals", headers=auth).json()
    assert body["baseline"] is None


def test_an_unreadable_baseline_does_not_break_the_dashboard(client, auth, baseline,
                                                             db_session):
    """The runs are still worth showing."""
    baseline.write_text("{ not json")
    _run(db_session, label="full", macro_f1=0.9)
    db_session.commit()

    body = client.get("/admin/evals", headers=auth).json()
    assert body["baseline"] is None
    assert len(body["runs"]) == 1


# ── runs and the three-column comparison ────────────────────────────────────


def test_the_latest_run_of_each_configuration_is_surfaced(client, auth, baseline,
                                                          db_session):
    """The three columns of the Phase 3 report: no model, model without retrieval,
    model with retrieval."""
    from datetime import timedelta

    now = utcnow()
    _run(db_session, label="keyword", macro_f1=0.40, started=now - timedelta(hours=3))
    _run(db_session, label="llm_only", macro_f1=0.81, started=now - timedelta(hours=2))
    _run(db_session, label="full", macro_f1=0.88, started=now - timedelta(hours=1))
    _run(db_session, label="full", macro_f1=0.93, started=now)
    db_session.commit()

    latest = client.get("/admin/evals", headers=auth).json()["latest_by_config"]
    assert latest == {"keyword": 0.40, "llm_only": 0.81, "full": 0.93}, (
        "the newest run of each config wins"
    )


def test_runs_are_newest_first_with_their_metrics(client, auth, baseline, db_session):
    from datetime import timedelta

    _run(db_session, label="keyword", macro_f1=0.4, started=utcnow() - timedelta(hours=1))
    _run(db_session, label="full", macro_f1=0.93)
    db_session.commit()

    runs = client.get("/admin/evals", headers=auth).json()["runs"]
    assert [r["config_label"] for r in runs] == ["full", "keyword"]
    assert runs[0]["metrics"][0]["metric"] == "macro_f1"
    assert runs[0]["metrics"][0]["detail"] == {"n": 70}


def test_an_unmeasured_metric_is_absent_rather_than_zero(client, auth, baseline,
                                                          db_session):
    """A metric with no samples is not 0.0, and the harness enforces that by not
    writing the row at all — `EvalResult.value` is NOT NULL precisely so an
    unmeasured figure cannot be stored as one. This asserts the consequence a reader
    has to understand: a missing metric means not measured, not zero."""
    run = _run(db_session, label="llm_only", macro_f1=0.8)
    db_session.commit()

    metrics = client.get("/admin/evals", headers=auth).json()["runs"][0]["metrics"]
    assert [m["metric"] for m in metrics] == ["macro_f1"]
    assert all(m["value"] is not None for m in metrics)


def test_a_run_with_no_metrics_still_appears(client, auth, baseline, db_session):
    """A sweep that died partway is exactly the one somebody wants to see."""
    _run(db_session, label="full")
    db_session.commit()
    assert client.get("/admin/evals", headers=auth).json()["runs"][0]["metrics"] == []


# ── access ──────────────────────────────────────────────────────────────────


def test_the_dashboard_needs_an_officer(client, db_session, baseline):
    """Not tenant-scoped — an eval run belongs to no municipality — but it exposes
    how well the system actually performs, which is not for the public."""
    assert client.get("/admin/evals").status_code == 401
    citizen = User(email="c@example.com", name="C", role="citizen",
                   password_hash=hash_password("pw"))
    db_session.add(citizen)
    db_session.commit()
    token = create_access_token(user_id=citizen.id, role="citizen")
    assert client.get("/admin/evals",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 403
