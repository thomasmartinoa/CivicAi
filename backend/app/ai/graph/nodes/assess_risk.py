"""Score how urgently the municipality must act.

Unlike v1, where "risk" was a lookup keyed only on category — so a pothole
outside a school gate and one on an empty service road both scored 60 — the
model sees the specific report and the category together.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def _media_context(state: ComplaintState) -> str:
    return "\n".join(f"[{i.media_type}] {i.text}" for i in state["media_insights"])


def assess_risk_node(state: ComplaintState, config: RunnableConfig) -> dict:
    chain = deps_from_config(config).require("risk_chain")
    classification = state["classification"]

    try:
        result = chain.invoke({
            "description": state["description"],
            "category": classification.category.value,
            "media_context": _media_context(state),
        })
    except Exception as exc:
        return {
            "errors": [f"assess_risk: {exc}"],
            "decision_log": [NodeDecision(node="assess_risk", summary=f"failed: {exc}")],
        }

    return {
        "risk": result,
        "decision_log": [NodeDecision(
            node="assess_risk",
            summary=f"{result.risk_level.value} ({result.priority_score}/100)",
        )],
    }
