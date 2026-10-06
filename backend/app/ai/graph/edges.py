"""Conditional-edge predicates.

Each is a pure function of state, so the routing rules are unit-testable
without building a graph. Every one fails closed: if the evidence a decision
needs is absent, the run ends rather than proceeding on nothing.
"""

from langgraph.graph import END

from app.ai.graph.state import ComplaintState

# Below this, the classification is not trusted on its own and the run takes
# the investigate loop, which retrieves the taxonomy and asks again.
CONFIDENCE_THRESHOLD = 0.7

# How many times investigate may run before the best available answer
# proceeds anyway. A stuck loop is worse than a low-confidence category the
# officer can see and correct.
MAX_INVESTIGATE_TURNS = 3


def after_validate(state: ComplaintState) -> str:
    validation = state["validation"]
    if validation is None or not validation.is_valid:
        return END
    return "classify"


def after_classify(state: ComplaintState) -> str:
    """Confident classifications proceed; unsure ones are investigated.

    Fails closed on a missing classification. Does not check state["errors"]:
    that field accumulates via an operator.add reducer and is never cleared, so
    an unrelated upstream soft error (a failed geocode, a bad media file) would
    otherwise still be sitting there and end a run that has everything this
    node needs."""
    classification = state["classification"]
    if classification is None:
        return END
    if classification.confidence < CONFIDENCE_THRESHOLD:
        return "investigate"
    return "assess_risk"


def after_investigate(state: ComplaintState) -> str:
    """Loop until confident or out of turns; then proceed with what we have."""
    classification = state["classification"]
    if classification is None:
        return END
    if classification.confidence >= CONFIDENCE_THRESHOLD:
        return "assess_risk"
    if state["investigate_turns"] >= MAX_INVESTIGATE_TURNS:
        return "assess_risk"
    return "investigate"


def after_assess_risk(state: ComplaintState) -> str:
    """Fail closed: work_order reads state["risk"] unconditionally, so a failed
    assessment must not reach it. Does not check state["errors"] for the same
    reason as after_classify: it is a run-wide accumulator, not this node's."""
    if state["risk"] is None:
        return END
    return "route"
