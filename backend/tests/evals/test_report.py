"""The report is the deliverable. These tests are mostly about what it must
*refuse* to print: a fabricated cost, a 0.00 that was never measured, an error
count hidden in a denominator.
"""

import pytest

from app.constants import Category, RiskLevel
from app.evals.report import ConfigurationSummary, render_report
from app.evals.usage import CostRates, estimated_cost, load_cost_rates


def _summary(label, **over):
    base = dict(
        label=label,
        items=10,
        errored=0,
        reused=0,
        metrics={
            "classification_accuracy": 0.8,
            "macro_f1": 0.72,
            "department_accuracy": 0.8,
            "risk_band_accuracy": 0.6,
            "priority_mae": 11.4,
            "invalid_precision": 1.0,
            "invalid_recall": 0.5,
            "latency_p95_ms": 61000,
        },
        confusion={"ROADS": {"ROADS": 4, "WATER": 1}, "WATER": {"ROADS": 0, "WATER": 5}},
        per_tag={"injection": 1.0, "junk": 0.5},
        input_tokens=1200,
        output_tokens=340,
        cost=None,
    )
    return ConfigurationSummary(**{**base, **over})


def _provenance(**over):
    base = dict(dataset_name="golden_v1", dataset_hash="abc123def456", git_sha="a" * 40,
                graph_version="2b.0", prompt_versions={"classify": "v2", "assess_risk": "v2"},
                models={"flash": "gemini-3.5-flash-lite", "strong": "gemini-3.5-flash"},
                requests_per_second=2.0, generated_at="2026-09-28T09:00:00Z")
    return {**base, **over}


def test_the_report_puts_the_three_configurations_side_by_side():
    text = render_report([_summary("keyword"), _summary("llm_only"), _summary("full")],
                         provenance=_provenance())
    header = next(line for line in text.splitlines() if "keyword" in line and "full" in line)
    assert header.index("keyword") < header.index("llm_only") < header.index("full")


def test_a_metric_the_configuration_cannot_produce_says_not_applicable():
    """v1's keyword path has no risk model. 0.00 would read as "measured, and
    terrible"."""
    keyword = _summary("keyword", metrics={"classification_accuracy": 0.5,
                                           "risk_band_accuracy": None,
                                           "priority_mae": None})
    text = render_report([keyword], provenance=_provenance())
    risk_row = next(line for line in text.splitlines() if line.startswith("| Risk band accuracy"))
    mae_row = next(line for line in text.splitlines() if line.startswith("| Priority MAE"))
    assert "not applicable" in risk_row, risk_row
    assert "not applicable" in mae_row, mae_row
    assert "0.00" not in risk_row and "0.0" not in mae_row


def test_cost_says_not_configured_when_there_are_no_rates():
    """No default rates anywhere: an invented per-token price is the number most
    likely to end up misquoted in a README."""
    text = render_report([_summary("full", cost=None)], provenance=_provenance())
    assert "not configured" in text


def test_cost_is_printed_when_rates_exist():
    text = render_report([_summary("full", cost=0.0123)], provenance=_provenance())
    assert "0.0123" in text or "0.012" in text


def test_the_report_carries_provenance():
    text = render_report([_summary("full")], provenance=_provenance())
    for needle in ("golden_v1", "abc123def456", "a" * 12, "2b.0", "classify v2",
                   "gemini-3.5-flash-lite", "2.0"):
        assert needle in text, f"provenance is missing {needle!r}"


def test_the_report_states_how_many_items_errored():
    """Three failures out of a hundred belong on the page, not folded into the
    denominator where the accuracy looks unaffected."""
    text = render_report([_summary("full", items=100, errored=3)], provenance=_provenance())
    assert "3" in text and "errored" in text.lower()
    assert "Items attempted" in text


def test_the_report_says_when_predictions_were_reused_from_a_resumed_run():
    """A resumed sweep can straddle a prompt change, so the reader has to know
    the numbers are not all from one sitting."""
    text = render_report([_summary("full", reused=40)], provenance=_provenance())
    assert "40" in text and "reused" in text.lower()


def test_latency_is_labelled_as_wall_clock_with_the_rate_limit_beside_it():
    """61s per item is mostly free-tier waiting. Printing it as "latency" with no
    context invites it being read as model speed."""
    text = render_report([_summary("full")], provenance=_provenance())
    assert "wall clock" in text.lower()
    assert "2.0" in text, "the requests-per-second setting must be on the page"


def test_the_confusion_matrix_is_rendered_for_each_configuration():
    text = render_report([_summary("full")], provenance=_provenance())
    assert "ROADS" in text and "WATER" in text


def test_per_tag_accuracy_shows_the_slices_that_matter():
    text = render_report([_summary("full")], provenance=_provenance())
    assert "injection" in text and "junk" in text


def test_the_routing_column_is_marked_as_derivative():
    """In v2 the seeded departments come from CATEGORY_DEPARTMENT, so routing
    accuracy is a function of classification accuracy. Printing it as an
    independent metric would overstate what was measured."""
    text = render_report([_summary("full")], provenance=_provenance())
    assert "derived from the category" in text.lower()


# ── cost rates ──────────────────────────────────────────────────────────────


def test_there_are_no_default_cost_rates(tmp_path):
    assert load_cost_rates(tmp_path / "missing.json") is None


def test_rates_are_loaded_when_the_operator_wrote_them(tmp_path):
    path = tmp_path / "rates.json"
    path.write_text('{"source": "quoted 2026-09", "per_million_input": 0.10, "per_million_output": 0.40}')
    rates = load_cost_rates(path)
    assert isinstance(rates, CostRates)
    assert rates.source == "quoted 2026-09"


def test_a_rates_file_with_no_source_is_refused(tmp_path):
    """A price with no provenance is a number someone will have to defend later."""
    path = tmp_path / "rates.json"
    path.write_text('{"per_million_input": 0.10, "per_million_output": 0.40}')
    with pytest.raises(ValueError, match="source"):
        load_cost_rates(path)


def test_cost_is_none_without_rates_and_computed_with_them():
    assert estimated_cost(1_000_000, 1_000_000, None) is None
    rates = CostRates(source="test", per_million_input=0.10, per_million_output=0.40)
    assert estimated_cost(1_000_000, 1_000_000, rates) == pytest.approx(0.50)
    assert estimated_cost(None, None, rates) is None
