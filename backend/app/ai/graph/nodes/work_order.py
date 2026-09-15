"""Draft the work order: SLA window, cost, materials.

The SLA deadline is computed here, not asked of the model — an LLM has no
reliable notion of "now", which is why WorkOrderDraft has no sla_deadline field.

The cost is grounded, not looked up. v1 priced every ROADS complaint at
5000 × a risk multiplier from two dictionaries. Here the node retrieves the
municipal rate card and the category's SOP materials section, and a structured
chain picks line items and quantities and cites them. When the chain or the
index is unavailable the cost is honestly None and cost_basis says why — the
SLA window never waits on the model.
"""

from datetime import timedelta

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.retrieval import format_evidence, retrieve
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision, WorkOrderDraft
from app.constants import RiskLevel
from app.db.base import utcnow

SLA_HOURS: dict[RiskLevel, int] = {
    RiskLevel.CRITICAL: 4,
    RiskLevel.HIGH: 24,
    RiskLevel.MEDIUM: 72,
    RiskLevel.LOW: 168,
}


def work_order_node(state: ComplaintState, config: RunnableConfig) -> dict:
    deps = deps_from_config(config)
    category = state["classification"].category
    risk = state["risk"]
    routing = state["routing"]
    sla_hours = SLA_HOURS[risk.risk_level]
    deadline = utcnow() + timedelta(hours=sla_hours)

    # Rate card first, then the SOP's materials section for this category; the
    # rate card carries no category, so it needs its own doc_type filter.
    rates = retrieve(deps.policy_retriever, f"unit rates for {category.value} repair materials and labour",
                     node="work_order", k=3, filters={"doc_type": "rate_card"})
    sop = retrieve(deps.policy_retriever, f"typical materials and cost drivers for {category.value}",
                   node="work_order", k=1, filters={"doc_type": "sop", "category": category.value})
    evidence = rates.chunks + sop.chunks
    errors = [rates.error] if rates.error else []

    estimated_cost = None
    materials = "To be determined on site inspection"
    try:
        chain = deps.require("work_order_chain")
        estimate = chain.invoke({
            "category": category.value,
            "risk_level": risk.risk_level.value,
            "description": state["description"],
            "evidence": format_evidence(evidence),
        })
        estimated_cost = estimate.estimated_cost
        cost_basis = estimate.cost_basis
        materials = estimate.materials
    except Exception as exc:
        errors.append(f"work_order: {exc}")
        cost_basis = f"estimate unavailable: {exc}"

    draft = WorkOrderDraft(
        sla_hours=sla_hours,
        estimated_cost=estimated_cost,
        cost_basis=cost_basis,
        materials=materials,
        summary=(
            f"{category.value} | {risk.risk_level.value} ({risk.priority_score}/100) | "
            f"{routing.department_name if routing else 'unrouted'}"
        ),
    )
    cost_text = f"est. {estimated_cost:.0f}" if estimated_cost is not None else "no estimate"
    return {
        "work_order": draft,
        "evidence": evidence,
        "errors": errors,
        "decision_log": [NodeDecision(
            node="work_order",
            summary=f"SLA {sla_hours}h, due {deadline.isoformat()}, {cost_text}",
        )],
    }
