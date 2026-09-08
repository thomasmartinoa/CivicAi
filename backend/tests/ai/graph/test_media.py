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


def test_the_insight_takes_path_and_type_from_the_node_not_the_model(make_config):
    """VisionObservation has no file_path or media_type field, so those can only
    come from the node. The model cannot invent a path it was never asked for."""
    obs = VisionObservation(text="a pothole", shows_infrastructure_problem=True)
    update = analyse_media_node(_payload("uploads/real.jpg", "image"),
                                make_config(vision_chain=returns(obs)))

    assert "file_path" not in VisionObservation.model_fields
    assert "media_type" not in VisionObservation.model_fields
    assert update["media_insights"][0].file_path == "uploads/real.jpg"
    assert update["media_insights"][0].media_type == "image"


def test_the_chain_is_invoked_with_the_file_path(make_config):
    """The node's contract with its chain is {"file_path": str}. Turning that into
    the vision prompt's image_url/image_context is the adapter's job, wired in
    build_deps. Keeping file loading out of the node is what makes the node
    testable without touching disk."""
    seen = {}

    def capture(payload):
        seen.update(payload)
        return VisionObservation(text="x", shows_infrastructure_problem=True)

    from langchain_core.runnables import RunnableLambda

    analyse_media_node(_payload(), make_config(vision_chain=RunnableLambda(capture)))
    assert set(seen) == {"file_path"}


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
