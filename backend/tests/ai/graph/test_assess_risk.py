from langchain_core.runnables import RunnableLambda

from app.ai.graph.nodes.assess_risk import assess_risk_node
from app.ai.schemas import ClassificationResult, RiskAssessment
from app.constants import Category, RiskLevel
from tests.ai.graph.conftest import raises, returns
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


def _state(base_state):
    return {**base_state,
            "classification": ClassificationResult(category=Category.ROADS, confidence=0.9)}


def test_records_the_assessment(make_config, base_state):
    result = RiskAssessment(priority_score=80, risk_level=RiskLevel.CRITICAL)
    update = assess_risk_node(_state(base_state), make_config(risk_chain=returns(result)))
    assert update["risk"].priority_score == 80


def test_the_category_is_passed_to_the_model(make_config, base_state):
    seen = {}

    def capture(payload):
        seen.update(payload)
        return RiskAssessment(priority_score=50, risk_level=RiskLevel.MEDIUM)

    from langchain_core.runnables import RunnableLambda

    assess_risk_node(_state(base_state), make_config(risk_chain=RunnableLambda(capture)))
    assert seen["category"] == Category.ROADS.value


def test_a_model_failure_is_an_error(make_config, base_state):
    update = assess_risk_node(_state(base_state), make_config(risk_chain=raises(RuntimeError("x"))))
    assert update["errors"]


def _policy():
    return FakeRetriever([_hit("76-100 is critical: respond within 4 hours.", "sla_policy.md", ["SLA Policy", "Priority bands"])])


def _cases():
    return FakeRetriever([_hit("ROADS complaint in East: pothole near school. Resolved in 3 hours.", "case:abc", [], category="ROADS")])


def test_the_chain_sees_policy_and_precedent_as_numbered_evidence(make_config, base_state):
    seen = {}
    def capture(payload):
        seen.update(payload)
        return RiskAssessment(priority_score=80, risk_level=RiskLevel.CRITICAL)
    config = make_config(risk_chain=RunnableLambda(capture), policy_retriever=_policy(), cases_retriever=_cases())
    update = assess_risk_node(_state(base_state), config)
    assert "[1] sla_policy.md › SLA Policy › Priority bands" in seen["evidence"]
    assert "[2] case:abc" in seen["evidence"]
    assert [c.source for c in update["evidence"]] == ["sla_policy.md", "case:abc"]
    assert all(c.node == "assess_risk" for c in update["evidence"])


def test_precedent_is_filtered_to_the_category(make_config, base_state):
    cases = _cases()
    config = make_config(risk_chain=returns(RiskAssessment(priority_score=30, risk_level=RiskLevel.MEDIUM)),
                         policy_retriever=_policy(), cases_retriever=cases)
    assess_risk_node(_state(base_state), config)
    assert cases.calls[0]["filters"] == {"category": "ROADS"}


def test_no_cases_index_is_not_an_error(make_config, base_state):
    """Before the first resolved complaint there is no cases collection; that
    is normal, not a failure, and must not show up in the run's error list."""
    config = make_config(risk_chain=returns(RiskAssessment(priority_score=30, risk_level=RiskLevel.MEDIUM)),
                         policy_retriever=_policy())
    update = assess_risk_node(_state(base_state), config)
    assert update["errors"] == []
    assert [c.source for c in update["evidence"]] == ["sla_policy.md"]


def test_a_missing_policy_index_is_a_soft_error(make_config, base_state):
    config = make_config(risk_chain=returns(RiskAssessment(priority_score=30, risk_level=RiskLevel.MEDIUM)))
    update = assess_risk_node(_state(base_state), config)
    assert update["risk"].priority_score == 30
    assert update["errors"] == ["assess_risk: retrieval unavailable: no retriever configured"]
