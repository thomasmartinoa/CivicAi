"""Is this an infrastructure complaint the municipality should act on?

The distinction this node draws that v1 could not: a *rejection* is a business
outcome and sets `terminal_reason`; a *model failure* is an infrastructure
problem and appends to `errors`. v1 put both in one list, which is why a
correctly-rejected complaint was stored looking exactly like an unprocessed one.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision

MIN_DESCRIPTION_CHARS = 10


def validate_node(state: ComplaintState, config: RunnableConfig) -> dict:
    chain = deps_from_config(config).require("validate_chain")
    description = state["description"].strip()

    # Cheap guard first: no reason to spend a free-tier request on this.
    if len(description) < MIN_DESCRIPTION_CHARS:
        return {
            "terminal_reason": "Description too short to assess",
            "decision_log": [NodeDecision(node="validate", summary="rejected: too short")],
        }

    try:
        result = chain.invoke({"description": description})
    except Exception as exc:
        return {
            "errors": [f"validate: {exc}"],
            "decision_log": [NodeDecision(node="validate", summary=f"failed: {exc}")],
        }

    if not result.is_valid:
        reason = result.rejection_reason or "Not an infrastructure complaint"
        return {
            "validation": result,
            "terminal_reason": reason,
            "decision_log": [NodeDecision(node="validate", summary=f"rejected: {reason}")],
        }

    return {
        "validation": result,
        "terminal_reason": None,
        "decision_log": [NodeDecision(node="validate", summary="accepted")],
    }
