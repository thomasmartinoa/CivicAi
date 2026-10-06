import pytest

from app.ai.graph.nodes.validate import validate_node
from app.ai.schemas import ValidationResult
from tests.ai.graph.conftest import raises, returns


def test_accepts_an_infrastructure_complaint(make_config, base_state):
    result = ValidationResult(is_valid=True, what_happened="pothole on the main road")
    update = validate_node(base_state, make_config(validate_chain=returns(result)))

    assert update["validation"].is_valid is True
    assert update["terminal_reason"] is None
    assert update["decision_log"][0].node == "validate"


def test_rejects_a_non_infrastructure_complaint(make_config, base_state):
    result = ValidationResult(is_valid=False, rejection_reason="a dispute with a neighbour")
    update = validate_node(base_state, make_config(validate_chain=returns(result)))

    assert update["validation"].is_valid is False
    assert "neighbour" in update["terminal_reason"]


def test_rejection_is_not_recorded_as_an_error(make_config, base_state):
    """v1's worst bug: a rejection and a crash both went into `errors`, so the
    router overwrote a correctly-rejected complaint's status back to 'submitted'."""
    result = ValidationResult(is_valid=False, rejection_reason="not infrastructure")
    update = validate_node(base_state, make_config(validate_chain=returns(result)))

    assert update.get("errors", []) == []
    assert update["terminal_reason"]


def test_a_too_short_description_is_rejected_without_calling_the_model(make_config):
    """Cheap guards run before spending a request on the free tier."""
    from app.ai.graph.state import initial_state

    called = {"n": 0}

    def counting(_):
        called["n"] += 1
        return ValidationResult(is_valid=True)

    from langchain_core.runnables import RunnableLambda

    state = initial_state(complaint_id="c", tracking_id="CIV-T", raw_description="hi")
    update = validate_node(state, make_config(validate_chain=RunnableLambda(counting)))

    assert called["n"] == 0
    assert update["terminal_reason"]


def test_a_model_failure_becomes_an_error_not_a_rejection(make_config, base_state):
    """An outage must be distinguishable from a business decision."""
    update = validate_node(base_state, make_config(validate_chain=raises(RuntimeError("503"))))

    assert update["errors"]
    assert update.get("terminal_reason") is None
    assert update.get("validation") is None


def test_missing_chain_raises_an_actionable_error(base_state):
    from app.ai.graph.deps import GraphDeps, to_configurable

    config = to_configurable(GraphDeps(), thread_id="t")
    with pytest.raises(ValueError, match="validate_chain"):
        validate_node(base_state, config)
