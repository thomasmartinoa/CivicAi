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


def after_classify(state: ComplaintState) -> str:
    """Low confidence is recorded but does not branch until Phase 2 adds the
    retrieval loop. Fails closed on a missing classification, as elsewhere."""
    if state["errors"] or state["classification"] is None:
        return END
    return "assess_risk"


def after_assess_risk(state: ComplaintState) -> str:
    """Fail closed: work_order reads state["risk"] unconditionally, so a failed
    assessment must not reach it."""
    if state["errors"] or state["risk"] is None:
        return END
    return "route"
