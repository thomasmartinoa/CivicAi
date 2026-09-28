"""The runner, offline.

A stub configuration returns canned predictions, so these tests cover the parts
that would otherwise only be exercised by a two-hour sweep: the deterministic
slice, the predictions log, resume, and how errors and unmeasurable metrics reach
the report.
"""

import json

import pytest

from app.constants import CATEGORY_DEPARTMENT, Category, RiskLevel
from app.evals.configurations import Prediction
from app.evals.dataset import load_golden
from app.evals.run import CONFIGURATIONS, append_log, load_log, run, summarise


class StubConfiguration:
    """Answers from a canned map, counting how often it was asked."""

    label = "stub"
    answers: dict = {}
    calls: list = []

    def __init__(self):
        type(self).calls = []

    def predict(self, item):
        type(self).calls.append(item.id)
        return type(self).answers.get(item.id, Prediction(
            valid=item.expected_valid,
            category=item.expected_category,
            department=item.expected_department,
            risk_band=item.expected_risk_band,
            priority=item.expected_priority,
            latency_ms=5,
        ))


@pytest.fixture
def stub(monkeypatch):
    StubConfiguration.answers = {}
    monkeypatch.setitem(CONFIGURATIONS, "stub", StubConfiguration)
    return StubConfiguration


def _run(tmp_path, stub, **over):
    kwargs = dict(suite="core", config_labels=["stub"], limit=5, out_dir=tmp_path / "reports",
                  log_path=tmp_path / "log.jsonl", resume=False, write_db=False)
    kwargs.update(over)
    return run(**kwargs)


def test_a_report_is_written_and_names_the_configuration(tmp_path, stub):
    path = _run(tmp_path, stub)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "stub" in text
    assert "## Provenance" in text


def test_the_limit_takes_a_deterministic_slice(tmp_path, stub):
    """A random sample would make two --limit 10 runs incomparable."""
    _run(tmp_path, stub, limit=5)
    first = list(stub.calls)
    _run(tmp_path, stub, limit=5, log_path=tmp_path / "second.jsonl")
    assert stub.calls == first
    assert first == sorted(i.id for i in load_golden())[:5]


def test_every_prediction_is_logged_as_it_completes(tmp_path, stub):
    log = tmp_path / "log.jsonl"
    _run(tmp_path, stub, log_path=log)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(rows) == 5
    assert {r["config"] for r in rows} == {"stub"}
    assert all(r["dataset_hash"] for r in rows), "the log records which dataset it came from"


def test_resume_reuses_the_log_instead_of_calling_the_model(tmp_path, stub):
    """The reason this exists: a full sweep is two hours, and a 429 in the middle
    must not cost all of it."""
    log = tmp_path / "log.jsonl"
    _run(tmp_path, stub, log_path=log)
    assert len(stub.calls) == 5

    path = _run(tmp_path, stub, log_path=log, resume=True)
    assert stub.calls == [], "nothing should have been re-predicted"
    assert "5" in next(line for line in path.read_text().splitlines() if "reused" in line.lower())


def test_resume_only_fills_the_gaps(tmp_path, stub):
    log = tmp_path / "log.jsonl"
    _run(tmp_path, stub, log_path=log, limit=3)
    _run(tmp_path, stub, log_path=log, limit=5, resume=True)
    assert len(stub.calls) == 2, "only the two new items should have been predicted"


def test_a_logged_prediction_round_trips(tmp_path):
    log = tmp_path / "log.jsonl"
    original = Prediction(valid=True, category=Category.ROADS,
                          department=CATEGORY_DEPARTMENT[Category.ROADS],
                          risk_band=RiskLevel.HIGH, priority=60, latency_ms=1234,
                          input_tokens=100, output_tokens=20, error=None)
    append_log(log, config="full", item_id="std-roads-1", dataset="abc", prediction=original)
    restored = load_log(log)["full::std-roads-1"]
    assert restored.category is Category.ROADS
    assert restored.risk_band is RiskLevel.HIGH
    assert restored.priority == 60 and restored.latency_ms == 1234
    assert restored.input_tokens == 100


def test_an_errored_item_is_counted_and_not_scored(tmp_path, stub):
    items = sorted(load_golden(), key=lambda i: i.id)[:5]
    stub.answers = {items[0].id: Prediction(error="quota exceeded", latency_ms=3)}
    path = _run(tmp_path, stub)
    text = path.read_text(encoding="utf-8")
    errored_row = next(line for line in text.splitlines() if line.startswith("| Items errored"))
    scored_row = next(line for line in text.splitlines() if line.startswith("| Items scored"))
    assert "1" in errored_row
    assert "4" in scored_row, "the failed item must leave the denominator, visibly"


def test_metrics_a_configuration_cannot_produce_stay_none(tmp_path, stub):
    """The keyword column in miniature: no risk band anywhere means the risk rows
    are not applicable rather than 0.00."""
    items = sorted(load_golden(), key=lambda i: i.id)[:5]
    stub.answers = {
        i.id: Prediction(valid=True, category=i.expected_category,
                         department=i.expected_department, latency_ms=2)
        for i in items
    }
    path = _run(tmp_path, stub)
    risk_row = next(line for line in path.read_text().splitlines()
                    if line.startswith("| Risk band accuracy"))
    assert "not applicable" in risk_row


def test_the_injection_slice_scores_the_band_not_the_refusal():
    """An injection item is correct when the band the text tried to override did
    not move."""
    items = [i for i in load_golden() if "injection" in i.tags][:2]
    obeyed = [Prediction(valid=True, category=i.expected_category, department=i.expected_department,
                         risk_band=RiskLevel.CRITICAL, priority=99, latency_ms=1) for i in items]
    summary = summarise("stub", items, obeyed, reused=0, rates=None)
    assert summary.per_tag["injection"] == 0.0, "obeying the injection must score zero"

    held = [Prediction(valid=True, category=i.expected_category, department=i.expected_department,
                       risk_band=i.expected_risk_band, priority=i.expected_priority, latency_ms=1)
            for i in items]
    assert summarise("stub", items, held, reused=0, rates=None).per_tag["injection"] == 1.0


def test_token_totals_are_none_when_the_provider_reported_nothing(tmp_path, stub):
    summary = summarise("stub", [], [], reused=0, rates=None)
    assert summary.input_tokens is None
    assert summary.cost is None, "no rates and no tokens means no cost, not zero"


def test_a_configuration_with_no_risk_model_is_not_applicable_on_the_injection_slice():
    """Caught by the first real keyword run: the slice scored 0.00 because the
    baseline produces no band at all, which reads as "it obeyed every injection"
    when in fact it was never asked. Silence is not a wrong answer."""
    items = [i for i in load_golden() if "injection" in i.tags][:3]
    no_risk_model = [Prediction(valid=True, category=i.expected_category,
                                department=i.expected_department, risk_band=None, latency_ms=1)
                     for i in items]
    assert summarise("keyword", items, no_risk_model, reused=0, rates=None).per_tag["injection"] is None
