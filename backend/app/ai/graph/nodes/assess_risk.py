"""Score how urgently the municipality must act.

Unlike v1, where "risk" was a lookup keyed only on category — so a pothole
outside a school gate and one on an empty service road both scored 60 — the
model sees the specific report and the category together.

From Phase 2b it also sees evidence: the SLA policy's priority bands, and
precedent cases with their real resolution times and costs when a cases index
exists. The precedents are what let the score reflect outcomes rather than
constants. The cases index is optional — it does not exist until the first
complaint is resolved — so its absence is not an error; the policy index is
expected, so its absence is a soft error like everywhere else.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.retrieval import format_evidence, retrieve
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def _media_context(state: ComplaintState) -> str:
    return "\n".join(f"[{i.media_type}] {i.text}" for i in state["media_insights"])


def assess_risk_node(state: ComplaintState, config: RunnableConfig) -> dict:
    deps = deps_from_config(config)
    chain = deps.require("risk_chain")
    classification = state["classification"]
    category = classification.category.value

    policy = retrieve(deps.policy_retriever, "priority bands and response windows by risk level",
                      node="assess_risk", k=2, filters={"doc_type": "sla_policy"})
    evidence = list(policy.chunks)
    errors = [policy.error] if policy.error else []
    if deps.cases_retriever is not None:
        cases = retrieve(deps.cases_retriever, state["description"],
                         node="assess_risk", k=3, filters={"category": category})
        evidence.extend(cases.chunks)
        if cases.error:
            errors.append(cases.error)

    try:
        result = chain.invoke({
            "description": state["description"],
            "category": category,
            "media_context": _media_context(state),
            "evidence": format_evidence(evidence),
        })
    except Exception as exc:
        return {
            "errors": errors + [f"assess_risk: {exc}"],
            "evidence": evidence,
            "decision_log": [NodeDecision(node="assess_risk", summary=f"failed: {exc}")],
        }

    return {
        "risk": result,
        "evidence": evidence,
        "errors": errors,
        "decision_log": [NodeDecision(
            node="assess_risk",
            summary=f"{result.risk_level.value} ({result.priority_score}/100)",
        )],
    }
