"""The three columns of the report, behind one interface.

Every test here is offline: the LLM configurations take an injected GraphDeps, so
the nodes run their real code paths against fake chains. What is being tested is
the wiring — which prompt version, which retrievers, what happens on failure —
not the model.
"""

import inspect

import pytest

from app.ai.graph.deps import GraphDeps
from app.ai.schemas import ClassificationResult, RiskAssessment, ValidationResult
from app.constants import CATEGORY_DEPARTMENT, Category, RiskLevel
from app.evals.configurations import (
    FullConfiguration, KeywordConfiguration, LlmOnlyConfiguration, Prediction,
)
from app.evals.dataset import GoldenItem
from tests.ai.graph.conftest import raises, returns
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


def _item(description, **over):
    defaults = dict(id="t-1", description=description, expected_valid=True,
                    expected_category=Category.ROADS,
                    expected_department=CATEGORY_DEPARTMENT[Category.ROADS],
                    expected_risk_band=RiskLevel.HIGH, expected_priority=60, tags=())
    return GoldenItem(**{**defaults, **over})


def _deps(**over):
    """Happy-path fakes for the two LLM configurations."""
    base = dict(
        validate_chain=returns(ValidationResult(is_valid=True, rejection_reason=None)),
        classify_chain=returns(ClassificationResult(category=Category.ROADS, confidence=0.9)),
        risk_chain=returns(RiskAssessment(priority_score=58, risk_level=RiskLevel.HIGH)),
    )
    return GraphDeps(**{**base, **over})


# ── the interface every configuration honours ───────────────────────────────


def test_every_configuration_has_a_label_and_predicts():
    for configuration in (KeywordConfiguration(), LlmOnlyConfiguration(deps=_deps()),
                          FullConfiguration(deps=_deps())):
        assert configuration.label
        prediction = configuration.predict(_item("there is a pothole on the main road"))
        assert isinstance(prediction, Prediction)
        assert prediction.latency_ms >= 0


def test_the_labels_are_distinct_and_stable():
    """They become column headers and config_label on every EvalRun row."""
    labels = {KeywordConfiguration().label, LlmOnlyConfiguration(deps=_deps()).label,
              FullConfiguration(deps=_deps()).label}
    assert labels == {"keyword", "llm_only", "full"}


# ── the v1 baseline ─────────────────────────────────────────────────────────


def test_the_keyword_configuration_reports_what_it_cannot_do():
    """v1's keyword path had no validity check and no risk model. Those cells
    must be None so the report says "not applicable" rather than implying it
    scored zero."""
    prediction = KeywordConfiguration().predict(_item("large pothole on the main road"))
    assert prediction.category is Category.ROADS
    assert prediction.department == CATEGORY_DEPARTMENT[Category.ROADS]
    assert prediction.valid is True, "v1 assessed every complaint as actionable"
    assert prediction.risk_band is None
    assert prediction.priority is None
    assert prediction.evidence == []


def test_the_keyword_configuration_calls_no_model_and_needs_no_key():
    source = inspect.getsource(KeywordConfiguration)
    for forbidden in ("build_structured", "invoke", "retrieve"):
        assert forbidden not in source, f"the baseline must stay pure: found {forbidden!r}"


def test_the_keyword_baseline_accepts_junk_which_is_the_finding():
    """It has no validity notion, so a noisy-neighbour complaint is classified
    anyway. The invalid-complaint precision column is where that shows up."""
    prediction = KeywordConfiguration().predict(
        _item("my neighbour plays loud music till 2am", expected_valid=False,
              expected_category=None, expected_department=None,
              expected_risk_band=None, expected_priority=None)
    )
    assert prediction.valid is True
    assert prediction.category is not None


# ── the middle column: no retrieval ─────────────────────────────────────────


def test_the_llm_only_configuration_passes_no_retriever():
    """The whole point of this column: every node takes its documented
    soft-failure path and grounds nothing."""
    configuration = LlmOnlyConfiguration(deps=_deps())
    assert configuration.deps.policy_retriever is None
    assert configuration.deps.cases_retriever is None
    prediction = configuration.predict(_item("there is a pothole on the main road"))
    assert prediction.evidence == []
    assert prediction.category is Category.ROADS


def test_the_llm_only_configuration_uses_the_ungrounded_prompt_versions():
    """classify v1 and assess_risk v1 were kept registered through Phase 2b for
    exactly this comparison; using LATEST here would make the two LLM columns
    differ only by retrieval-in-the-prompt, not by grounding."""
    assert LlmOnlyConfiguration.PROMPT_VERSIONS == {"classify": "v1", "assess_risk": "v1"}


def test_the_full_configuration_uses_the_current_prompts_and_both_retrievers():
    from app.ai.prompts import LATEST

    cases = FakeRetriever([_hit("ROADS in East: resolved in 5 hours.", "case:1", tenant_id="t-1")])
    policy = FakeRetriever([_hit("76-100 is critical.", "sla_policy.md", ["SLA Policy", "Priority bands"])])
    configuration = FullConfiguration(deps=_deps(policy_retriever=policy, cases_retriever=cases))
    assert configuration.PROMPT_VERSIONS == {}, "full follows LATEST"
    assert LATEST["classify"] == "v2", "if this changes, the comparison changed"

    prediction = configuration.predict(_item("there is a pothole on the main road"))
    assert prediction.evidence, "the full configuration must ground its risk assessment"
    assert any(c.node == "assess_risk" for c in prediction.evidence)


# ── failure handling ────────────────────────────────────────────────────────


def test_a_chain_failure_becomes_a_recorded_error_not_a_crash():
    """One bad item out of a hundred must not lose the other ninety-nine, and the
    report states how many errored rather than hiding them in the denominator."""
    configuration = LlmOnlyConfiguration(deps=_deps(classify_chain=raises(RuntimeError("quota"))))
    prediction = configuration.predict(_item("there is a pothole on the main road"))
    assert prediction.error is not None and "quota" in prediction.error
    assert prediction.category is None


def test_a_rejected_complaint_stops_before_classification():
    """A complaint the model rejects has no category by definition — scoring one
    would measure the classifier on something it never saw."""
    configuration = LlmOnlyConfiguration(deps=_deps(
        validate_chain=returns(ValidationResult(is_valid=False, rejection_reason="a neighbour dispute")),
        classify_chain=raises(AssertionError("must not be invoked")),
    ))
    prediction = configuration.predict(_item("my neighbour plays loud music"))
    assert prediction.valid is False
    assert prediction.category is None
    assert prediction.error is None, "a rejection is an outcome, not a failure"


def test_a_validation_failure_is_an_error_not_a_rejection():
    """v1's headline bug, at eval level: a model outage must not be recorded as
    "the complaint was junk"."""
    configuration = LlmOnlyConfiguration(deps=_deps(validate_chain=raises(RuntimeError("503"))))
    prediction = configuration.predict(_item("there is a pothole on the main road"))
    assert prediction.error is not None and "503" in prediction.error
    assert prediction.valid is None, "validity is unknown, not False"


# ── the cache, and the database ─────────────────────────────────────────────


def test_every_chain_is_built_with_the_cache_switched_off(monkeypatch):
    """A cache hit would make latency and token counts fiction, and cache_for
    keys on (prompt, version) — which does not separate llm_only from full, since
    they share the validate prompt.

    Asserted on the calls rather than on the source text: a docstring explaining
    the rule would satisfy a grep.
    """
    from app.ai import llm

    calls = []

    def record(task, schema, prompt_name, prompt_version=None, *, cache=None, retries=3):
        calls.append({"prompt": prompt_name, "version": prompt_version,
                      "cache": cache, "retries": retries})
        return returns(None)

    monkeypatch.setattr(llm, "build_structured", record)

    for configuration in (LlmOnlyConfiguration(), FullConfiguration()):
        calls.clear()
        configuration._build_deps()
        assert calls, f"{configuration.label} built no chains"
        assert all(c["cache"] is None for c in calls), f"{configuration.label}: {calls}"
        assert all(c["retries"] == 1 for c in calls), (
            "the sweep is its own retry loop: nine stacked attempts cost two minutes "
            f"per item against a provider that is down — {calls}"
        )


def test_the_ungrounded_column_pins_its_prompt_versions(monkeypatch):
    """llm_only must ask for v1 explicitly; full must pass None so LATEST wins."""
    from app.ai import llm

    calls = {}

    def record(task, schema, prompt_name, prompt_version=None, *, cache=None, retries=3):
        calls[prompt_name] = prompt_version
        return returns(None)

    monkeypatch.setattr(llm, "build_structured", record)

    LlmOnlyConfiguration()._build_deps()
    assert calls == {"validate": None, "classify": "v1", "assess_risk": "v1"}

    calls.clear()
    FullConfiguration()._build_deps()
    assert calls == {"validate": None, "classify": None, "assess_risk": None}


def test_predict_writes_nothing_to_the_database(db_session):
    """An eval must not leave a hundred complaints in the operator's tables."""
    from app.db.models.complaint import Complaint
    from app.db.models.ai import AgentRun

    configuration = FullConfiguration(deps=_deps(session_factory=lambda: db_session))
    configuration.predict(_item("there is a pothole on the main road"))
    assert db_session.query(Complaint).count() == 0
    assert db_session.query(AgentRun).count() == 0


def test_the_department_comes_from_the_same_map_for_every_configuration():
    """Routing accuracy in v2 is a deterministic function of the category: the
    seeded Department rows are built from CATEGORY_DEPARTMENT. Using one lookup
    for all three columns keeps them comparable, and the report has to say the
    metric is derivative rather than independent signal."""
    for configuration in (KeywordConfiguration(), LlmOnlyConfiguration(deps=_deps()),
                          FullConfiguration(deps=_deps())):
        prediction = configuration.predict(_item("large pothole on the main road"))
        if prediction.category:
            assert prediction.department == CATEGORY_DEPARTMENT[prediction.category]
