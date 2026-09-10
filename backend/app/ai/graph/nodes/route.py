"""Pick the owning department and the best-placed contractor.

Two v1 defects fixed structurally:

- The department comes from `Department.categories`, the JSON column v1
  declared, seeded, and then ignored in favour of a hardcoded dict that drifted
  until CONSTRUCTION and SEWAGE pointed at departments that did not exist.
- Contractor scoring lives here once. v1 copy-pasted the identical loop into
  three files, so changing a weight meant remembering all three.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.constants import Category, JurisdictionLevel
from app.ai.schemas import NodeDecision, RoutingDecision

# Weights are deliberately explicit rather than tuned. Specialisation dominates,
# then track record, then availability, then locality as a tie-breaker.
SPECIALISATION_WEIGHT = 40.0
RATING_WEIGHT = 6.0
WORKLOAD_ALLOWANCE = 20.0
WORKLOAD_PENALTY = 2.0
ZONE_BONUS = 10.0


def score_contractor(contractor, category: Category, district: str | None) -> float:
    score = 0.0
    if contractor.specializations and category.value in contractor.specializations:
        score += SPECIALISATION_WEIGHT
    score += (contractor.rating or 0.0) * RATING_WEIGHT
    score += max(0.0, WORKLOAD_ALLOWANCE - (contractor.active_workload or 0) * WORKLOAD_PENALTY)
    if district and contractor.zone and contractor.zone.lower() == district.lower():
        score += ZONE_BONUS
    return score


def _jurisdiction(state: ComplaintState) -> JurisdictionLevel:
    """The finest level we actually know, not the finest level that exists."""
    location = state["location"]
    if location is None:
        return JurisdictionLevel.CITY
    if location.ward:
        return JurisdictionLevel.WARD
    if location.block:
        return JurisdictionLevel.BLOCK
    if location.district:
        return JurisdictionLevel.DISTRICT
    return JurisdictionLevel.CITY


def route_node(state: ComplaintState, config: RunnableConfig) -> dict:
    from app.db.models.core import Contractor, Department

    category = state["classification"].category
    district = state["location"].district if state["location"] else None
    tenant_id = state["tenant_id"]

    if not tenant_id:
        # Skipping the filter would span every tenant and route the complaint to
        # whichever one happens to list the category first.
        return {
            "errors": ["route: complaint has no tenant_id"],
            "decision_log": [NodeDecision(node="route", summary="failed: no tenant_id")],
        }

    session = deps_from_config(config).require("session_factory")()
    try:
        departments = session.query(Department).filter(Department.tenant_id == tenant_id)
        department = next(
            (d for d in departments.all() if category.value in (d.categories or [])), None
        )

        contractors = session.query(Contractor).filter(Contractor.tenant_id == tenant_id)
        ranked = sorted(
            contractors.all(), key=lambda c: score_contractor(c, category, district), reverse=True
        )
        contractor = ranked[0] if ranked else None
    finally:
        session.close()

    routing = RoutingDecision(
        department_name=department.name if department else "General Administration",
        department_id=department.id if department else None,
        contractor_id=contractor.id if contractor else None,
        contractor_name=contractor.name if contractor else None,
        jurisdiction_level=_jurisdiction(state),
        justification=(
            f"{category.value} is owned by "
            f"{department.name if department else 'no seeded department'}"
        ),
    )
    return {
        "routing": routing,
        "decision_log": [NodeDecision(
            node="route",
            summary=f"{routing.department_name} / {routing.contractor_name or 'no contractor'}",
        )],
    }
