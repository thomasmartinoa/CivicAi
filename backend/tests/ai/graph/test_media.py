from app.ai.graph.nodes.media import analyse_media_node
from app.ai.schemas import VisionObservation
from tests.ai.graph.conftest import raises, returns


def _payload(path="uploads/a.jpg", media_type="image"):
    return {"file_path": path, "media_type": media_type}


def test_an_image_becomes_a_media_insight(make_config):
    obs = VisionObservation(text="a deep pothole", shows_infrastructure_problem=True,
                            apparent_severity="severe")
    update = analyse_media_node(_payload(), make_config(vision_chain=returns(obs)))

    insight = update["media_insights"][0]
    assert insight.text == "a deep pothole"
    assert insight.file_path == "uploads/a.jpg"
    assert insight.media_type == "image"


def test_the_node_supplies_path_and_type_not_the_model(make_config):
    """The chain is invoked with file_path only; media_type is the node's business,
    not the model's. The node still supplies both into the final MediaInsight."""
    seen = {}

    def capture(payload):
        seen.update(payload)
        return VisionObservation(text="x", shows_infrastructure_problem=True)

    from langchain_core.runnables import RunnableLambda

    analyse_media_node(_payload(), make_config(vision_chain=RunnableLambda(capture)))
    assert "media_type" not in seen


def test_an_image_with_no_problem_produces_no_insight(make_config):
    """v1 decided this by checking whether the string 'No infrastructure issues'
    appeared in the model's prose."""
    obs = VisionObservation(text="an ordinary street", shows_infrastructure_problem=False)
    update = analyse_media_node(_payload(), make_config(vision_chain=returns(obs)))
    assert update["media_insights"] == []


def test_one_bad_file_does_not_fail_the_complaint(make_config):
    """A corrupt upload degrades the complaint; it must not end the run."""
    update = analyse_media_node(_payload(), make_config(vision_chain=raises(OSError("truncated"))))
    assert update["media_insights"] == []
    assert update["errors"]


def test_a_non_image_is_skipped_without_calling_the_model(make_config):
    called = {"n": 0}

    def counting(_):
        called["n"] += 1
        return VisionObservation(text="", shows_infrastructure_problem=False)

    from langchain_core.runnables import RunnableLambda

    update = analyse_media_node(_payload(media_type="video"),
                                make_config(vision_chain=RunnableLambda(counting)))
    assert called["n"] == 0
    assert update["media_insights"] == []
