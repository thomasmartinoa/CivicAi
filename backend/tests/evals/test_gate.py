"""The regression gate.

A gate that silently passes is not a gate, so every way of having nothing to
compare against is an explicit failure rather than a default pass.
"""

import json

import pytest

from app.evals.gate import (
    GATE_TOLERANCE, GateResult, NoBaseline, check_gate, load_baseline, write_baseline,
)


def test_a_small_drop_passes_and_a_larger_one_fails():
    """The tolerance is the provider's drift, not a licence to regress."""
    assert check_gate(current=0.80, baseline=0.82).passed is True
    assert check_gate(current=0.7999, baseline=0.82).passed is False


def test_the_tolerance_is_two_points():
    assert GATE_TOLERANCE == pytest.approx(0.02)


def test_the_failure_says_what_it_compared():
    result = check_gate(current=0.70, baseline=0.82)
    assert result.passed is False
    assert "0.70" in result.summary and "0.82" in result.summary
    assert "0.12" in result.summary or "12" in result.summary


def test_an_improvement_passes_but_does_not_move_the_baseline():
    """Auto-ratcheting would raise the bar on a lucky run and then fail every
    honest one after it."""
    result = check_gate(current=0.90, baseline=0.82)
    assert result.passed is True
    assert result.baseline == 0.82
    assert "improved" in result.summary.lower()


def test_a_missing_baseline_fails_loudly():
    """Not "passes because there is nothing to compare"."""
    with pytest.raises(NoBaseline, match="no baseline"):
        check_gate(current=0.8, baseline=None)


def test_an_unmeasured_current_score_fails_loudly():
    """macro_f1 is None when nothing was scored — an empty sweep must not pass
    the gate by producing no evidence of regression."""
    with pytest.raises(NoBaseline, match="not measured"):
        check_gate(current=None, baseline=0.82)


def test_the_baseline_round_trips_with_its_provenance(tmp_path):
    path = tmp_path / "core.json"
    write_baseline(path, macro_f1=0.79, dataset_hash="abc123", git_sha="f" * 40,
                   note="first honest measurement")
    loaded = load_baseline(path)
    assert loaded.macro_f1 == 0.79
    assert loaded.dataset_hash == "abc123"
    assert loaded.note == "first honest measurement"


def test_a_baseline_without_a_dataset_hash_is_refused(tmp_path):
    """A score means nothing without the dataset it was measured on: comparing
    against a baseline from a different golden set is worse than not comparing."""
    path = tmp_path / "core.json"
    path.write_text(json.dumps({"macro_f1": 0.79}))
    with pytest.raises(ValueError, match="dataset_hash"):
        load_baseline(path)


def test_a_missing_baseline_file_is_none_not_an_error(tmp_path):
    """Loading is allowed to find nothing; *checking* against nothing is not."""
    assert load_baseline(tmp_path / "absent.json") is None


def test_comparing_across_datasets_is_refused():
    """Same numbers, different golden set: the comparison is meaningless and must
    not quietly pass."""
    with pytest.raises(ValueError, match="dataset"):
        check_gate(current=0.80, baseline=0.82, current_dataset="abc", baseline_dataset="xyz")


def test_the_result_is_reportable():
    assert isinstance(check_gate(current=0.80, baseline=0.82), GateResult)


# ── the CLI exit code ───────────────────────────────────────────────────────


def test_gating_a_run_without_the_full_configuration_fails(capsys):
    """The gate is about what ships. A keyword-only run has nothing to gate on and
    must not exit zero as though it had passed."""
    from app.evals.report import ConfigurationSummary
    from app.evals.run import _gate

    keyword_only = [ConfigurationSummary(label="keyword", items=10, errored=0,
                                         metrics={"macro_f1": 0.54})]
    assert _gate(keyword_only, "abc123") == 1
    assert "nothing to gate" in capsys.readouterr().out


def test_gating_with_no_stored_baseline_exits_nonzero(monkeypatch, capsys):
    from app.evals import run as run_module
    from app.evals.report import ConfigurationSummary

    monkeypatch.setattr("app.evals.gate.load_baseline", lambda *a, **k: None)
    full = [ConfigurationSummary(label="full", items=10, errored=0, metrics={"macro_f1": 0.79})]
    assert run_module._gate(full, "abc123") == 1
    assert "FAIL" in capsys.readouterr().out


def test_gating_against_a_matching_baseline_exits_zero(monkeypatch, capsys):
    from app.evals import run as run_module
    from app.evals.gate import Baseline
    from app.evals.report import ConfigurationSummary

    monkeypatch.setattr("app.evals.gate.load_baseline",
                        lambda *a, **k: Baseline(macro_f1=0.79, dataset_hash="abc123"))
    full = [ConfigurationSummary(label="full", items=10, errored=0, metrics={"macro_f1": 0.78})]
    assert run_module._gate(full, "abc123") == 0
    assert "PASS" in capsys.readouterr().out


def test_gating_a_three_point_drop_exits_nonzero(monkeypatch, capsys):
    from app.evals import run as run_module
    from app.evals.gate import Baseline
    from app.evals.report import ConfigurationSummary

    monkeypatch.setattr("app.evals.gate.load_baseline",
                        lambda *a, **k: Baseline(macro_f1=0.79, dataset_hash="abc123"))
    full = [ConfigurationSummary(label="full", items=10, errored=0, metrics={"macro_f1": 0.76})]
    assert run_module._gate(full, "abc123") == 1
    assert "FAIL" in capsys.readouterr().out
