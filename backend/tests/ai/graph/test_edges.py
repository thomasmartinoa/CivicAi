from langgraph.graph import END

from app.ai.graph.edges import CONFIDENCE_THRESHOLD, after_validate
from app.ai.schemas import ValidationResult


def _state(**over):
    from app.ai.graph.state import initial_state

    return {**initial_state(complaint_id="c", tracking_id="T", raw_description="x" * 30), **over}


def test_valid_complaints_continue_to_classify():
    assert after_validate(_state(validation=ValidationResult(is_valid=True))) == "classify"


def test_rejected_complaints_go_straight_to_end():
    state = _state(validation=ValidationResult(is_valid=False, rejection_reason="no"),
                   terminal_reason="no")
    assert after_validate(state) == END


def test_an_errored_run_also_ends():
    """A model outage must not fall through into classification."""
    assert after_validate(_state(errors=["validate: 503"])) == END


def test_missing_validation_ends_rather_than_continuing():
    """Fail closed: never classify something that was never validated."""
    assert after_validate(_state()) == END


def test_the_confidence_threshold_is_a_named_constant():
    assert 0.0 < CONFIDENCE_THRESHOLD < 1.0
