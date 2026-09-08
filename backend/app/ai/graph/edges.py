"""Conditional-edge predicates.

Each is a pure function of state, so the routing rules are unit-testable
without building a graph. Every one fails closed: if the evidence a decision
needs is absent, the run ends rather than proceeding on nothing.
"""

from langgraph.graph import END

from app.ai.graph.state import ComplaintState

# Below this, the classification is not trusted on its own. Phase 2 sends these
# to the retrieval loop; until then it is recorded and the run continues.
CONFIDENCE_THRESHOLD = 0.7


def after_validate(state: ComplaintState) -> str:
    if state["errors"]:
        return END
    validation = state["validation"]
    if validation is None or not validation.is_valid:
        return END
    return "classify"
