from app.ai.graph.nodes.assess_risk import assess_risk_node
from app.ai.schemas import ClassificationResult, RiskAssessment
from app.constants import Category, RiskLevel
from tests.ai.graph.conftest import raises, returns


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
