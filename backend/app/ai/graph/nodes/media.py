"""Analyse one uploaded file. This is the Send fan-out target.

It receives a payload dict, not the whole state — that is what Send passes —
and returns an update that merges back through the media_insights reducer.

Whether an image shows a real problem is a typed boolean from the model, not a
substring search on its prose. v1 checked `if "No infrastructure issues" not in text`.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.schemas import MediaInsight

ANALYSABLE = {"image"}


def analyse_media_node(payload: dict, config: RunnableConfig) -> dict:
    file_path = payload["file_path"]
    media_type = payload["media_type"]

    if media_type not in ANALYSABLE:
        return {"media_insights": []}

    chain = deps_from_config(config).require("vision_chain")
    try:
        observation = chain.invoke({"file_path": file_path})
    except Exception as exc:
        # One unreadable upload degrades the complaint; it must not end the run.
        return {"media_insights": [], "errors": [f"analyse_media[{file_path}]: {exc}"]}

    if not observation.shows_infrastructure_problem:
        return {"media_insights": []}

    return {"media_insights": [MediaInsight(
        file_path=file_path,
        media_type=media_type,
        text=observation.text,
    )]}
