"""Normalise the submission and fan out over its media.

Geocoding failure is degradation, not termination: a complaint without a ward
is still a complaint. v1 made the same call and it was right.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def intake_node(state: ComplaintState, config: RunnableConfig) -> dict:
    coords = state["coords"]
    if coords is None:
        return {
            "location": None,
            "decision_log": [NodeDecision(node="intake", summary="no coordinates supplied")],
        }

    geocode = deps_from_config(config).require("geocode")
    try:
        location = geocode(coords.latitude, coords.longitude)
    except Exception as exc:
        return {
            "location": None,
            "errors": [f"intake: geocoding failed: {exc}"],
            "decision_log": [NodeDecision(node="intake", summary=f"geocoding failed: {exc}")],
        }

    return {
        "location": location,
        "decision_log": [NodeDecision(node="intake", summary=f"located in {location.district or 'unknown district'}")],
    }


def fan_out_media(state: ComplaintState):
    """One parallel branch per uploaded file, or straight on if there are none.

    Returns a node name rather than an empty list when there is no media: an
    empty Send list leaves the graph with nowhere to go.
    """
    media = state["media"]
    if not media:
        return "validate"
    return [
        Send("analyse_media", {"file_path": m.file_path, "media_type": m.media_type})
        for m in media
    ]
