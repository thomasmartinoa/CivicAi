"""Tell the citizen their complaint was processed.

**Idempotent by design.** Durability is bounded: a resumed run re-executes the
node it died in, and measurements show a SIGKILL can lose the tail entirely so
a whole run replays. Either way this node must not email the same citizen
twice, so it guards on a fact already in state rather than on an external flag.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision

NODE = "notify"


def _already_sent(state: ComplaintState) -> bool:
    return any(entry.node == NODE for entry in state["decision_log"])


def notify_node(state: ComplaintState, config: RunnableConfig) -> dict:
    if _already_sent(state):
        return {}

    notify = deps_from_config(config).require("notify")
    classification = state["classification"]

    try:
        notify(
            tracking_id=state["tracking_id"],
            complaint_id=state["complaint_id"],
            category=classification.category.value if classification else None,
            status="assigned",
        )
    except Exception as exc:
        # A failed notification must not lose a processed complaint.
        return {
            "errors": [f"notify: {exc}"],
            "decision_log": [NodeDecision(node=NODE, summary=f"failed: {exc}")],
        }

    return {"decision_log": [NodeDecision(node=NODE, summary="citizen notified")]}
