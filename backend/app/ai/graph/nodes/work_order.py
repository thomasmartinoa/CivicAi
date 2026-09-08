"""Draft the work order: SLA window, cost, materials.

The SLA deadline is computed here, not asked of the model — an LLM has no
reliable notion of "now", which is why WorkOrderDraft has no sla_deadline field.

Cost and materials are constants in this phase. Replacing them with retrieval
over a real rate card and past work orders is the substance of Phase 2; today
they are honest placeholders rather than a lookup table pretending to be
intelligence, and `cost_basis` records which they are.
"""

from datetime import timedelta

from langchain_core.runnables import RunnableConfig

from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision, WorkOrderDraft
from app.constants import Category, RiskLevel
from app.db.base import utcnow

SLA_HOURS: dict[RiskLevel, int] = {
    RiskLevel.CRITICAL: 4,
    RiskLevel.HIGH: 24,
    RiskLevel.MEDIUM: 72,
    RiskLevel.LOW: 168,
}

_BASE_COST: dict[Category, float] = {
    Category.ROADS: 5000.0, Category.ELECTRICITY: 3000.0, Category.WATER: 4000.0,
    Category.SANITATION: 2000.0, Category.PUBLIC_SPACES: 3000.0, Category.EDUCATION: 8000.0,
    Category.HEALTH: 6000.0, Category.FLOODING: 10000.0, Category.FIRE_HAZARD: 7000.0,
    Category.CONSTRUCTION: 15000.0, Category.STRAY_ANIMALS: 1000.0, Category.SEWAGE: 5000.0,
}

_RISK_MULTIPLIER: dict[RiskLevel, float] = {
    RiskLevel.CRITICAL: 2.0, RiskLevel.HIGH: 1.5, RiskLevel.MEDIUM: 1.0, RiskLevel.LOW: 0.8,
}


def work_order_node(state: ComplaintState, config: RunnableConfig) -> dict:
    category = state["classification"].category
    risk = state["risk"]
    routing = state["routing"]
    sla_hours = SLA_HOURS[risk.risk_level]
    deadline = utcnow() + timedelta(hours=sla_hours)
    cost = _BASE_COST[category] * _RISK_MULTIPLIER[risk.risk_level]

    draft = WorkOrderDraft(
        sla_hours=sla_hours,
        estimated_cost=cost,
        cost_basis="Category base rate x risk multiplier (placeholder until Phase 2 retrieval)",
        materials="To be determined on site inspection",
        summary=(
            f"{category.value} | {risk.risk_level.value} ({risk.priority_score}/100) | "
            f"{routing.department_name if routing else 'unrouted'}"
        ),
    )
    return {
        "work_order": draft,
        "decision_log": [NodeDecision(
            node="work_order",
            summary=f"SLA {sla_hours}h, due {deadline.isoformat()}, est. {cost:.0f}",
        )],
    }
