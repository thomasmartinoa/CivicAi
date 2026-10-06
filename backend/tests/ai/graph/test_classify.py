from app.ai.graph.nodes.classify import classify_node
from app.ai.schemas import ClassificationResult
from app.constants import Category
from tests.ai.graph.conftest import raises, returns


def test_records_the_classification(make_config, base_state):
    result = ClassificationResult(category=Category.ROADS, confidence=0.92, subcategory="Pothole")
    update = classify_node(base_state, make_config(classify_chain=returns(result)))

    assert update["classification"].category is Category.ROADS
    assert update["decision_log"][0].node == "classify"


def test_media_insights_are_passed_to_the_model(make_config, base_state):
    """v1 flattened image analysis into the description under a 'Voice
    transcription:' heading. Here it goes in as a separate labelled input."""
    from app.ai.schemas import MediaInsight

    seen = {}

    def capture(payload):
        seen.update(payload)
        return ClassificationResult(category=Category.ROADS, confidence=0.9)

    from langchain_core.runnables import RunnableLambda

    state = {**base_state, "media_insights": [
        MediaInsight(file_path="uploads/a.jpg", media_type="image", text="a deep pothole")
    ]}
    classify_node(state, make_config(classify_chain=RunnableLambda(capture)))

    assert "deep pothole" in seen["media_context"]
    assert seen["description"] == state["description"]


def test_a_model_failure_is_recorded_as_an_error(make_config, base_state):
    update = classify_node(base_state, make_config(classify_chain=raises(RuntimeError("boom"))))
    assert update["errors"]
    assert update.get("classification") is None
