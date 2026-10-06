"""Pick one of the twelve categories, with an honest confidence.

Media insights are passed as a separate labelled input rather than concatenated
into the description. v1 appended image analysis to the description under a
"Voice transcription:" heading, so every downstream step saw mislabelled text.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def _media_context(state: ComplaintState) -> str:
    return "\n".join(
        f"[{insight.media_type}] {insight.text}" for insight in state["media_insights"]
    )


def classify_node(state: ComplaintState, config: RunnableConfig) -> dict:
    chain = deps_from_config(config).require("classify_chain")

    try:
        result = chain.invoke({
            "description": state["description"],
            "media_context": _media_context(state),
        })
    except Exception as exc:
        return {
            "errors": [f"classify: {exc}"],
            "decision_log": [NodeDecision(node="classify", summary=f"failed: {exc}")],
        }

    return {
        "classification": result,
        "decision_log": [NodeDecision(
            node="classify",
            summary=f"{result.category.value} (confidence {result.confidence:.2f})",
        )],
    }
