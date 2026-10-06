"""Eval runs are rows before they are a report.

A report nobody can trace back to a dataset hash and a commit is a screenshot.
These tests cover the provenance, not the metrics.
"""

import pytest

from app.db.models.evaluation import EvalResult, EvalRun
from app.evals.record import git_sha, record_metrics, start_run


def test_a_run_records_what_it_was_run_against(db_session):
    run = start_run(db_session, suite="core", config_label="full",
                    dataset_name="golden_v1", dataset_hash="abc123")
    db_session.commit()

    stored = db_session.query(EvalRun).one()
    assert stored.suite == "core"
    assert stored.config_label == "full"
    assert stored.dataset_name == "golden_v1"
    assert stored.dataset_hash == "abc123"
    assert stored.started_at is not None
    assert stored.finished_at is None, "an unfinished run must be distinguishable"
    assert run.id == stored.id


def test_metrics_are_recorded_with_their_detail(db_session):
    run = start_run(db_session, suite="core", config_label="full",
                    dataset_name="golden_v1", dataset_hash="abc123")
    record_metrics(db_session, run, {
        "classification_accuracy": (0.84, {"n": 88}),
        "macro_f1": (0.79, None),
    })
    db_session.commit()

    rows = {r.metric: r for r in db_session.query(EvalResult).all()}
    assert rows["classification_accuracy"].value == 0.84
    assert rows["classification_accuracy"].detail_json == {"n": 88}
    assert rows["macro_f1"].value == 0.79
    assert all(r.eval_run_id == run.id for r in rows.values())


def test_a_finished_run_is_stamped(db_session):
    run = start_run(db_session, suite="core", config_label="full",
                    dataset_name="golden_v1", dataset_hash="abc123")
    record_metrics(db_session, run, {"macro_f1": (0.79, None)}, finished=True)
    db_session.commit()
    assert db_session.query(EvalRun).one().finished_at is not None


def test_a_metric_that_could_not_be_computed_is_not_recorded_as_zero(db_session):
    """None means "not measured". Writing 0.0 would make the gate compare against
    a failure that never happened."""
    run = start_run(db_session, suite="core", config_label="keyword",
                    dataset_name="golden_v1", dataset_hash="abc123")
    record_metrics(db_session, run, {"risk_band_accuracy": (None, {"reason": "no risk model"})})
    db_session.commit()

    rows = db_session.query(EvalResult).all()
    assert rows == [] or all(r.metric != "risk_band_accuracy" for r in rows), (
        "an unmeasured metric must not become a 0.0 row"
    )


def test_the_git_sha_is_a_sha_or_none():
    """None outside a checkout, never a crash: the harness must run from a
    tarball. It also never interpolates anything into the command."""
    sha = git_sha()
    assert sha is None or (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha))


def test_the_git_sha_is_none_when_git_is_not_a_repository(tmp_path):
    assert git_sha(cwd=tmp_path) is None
