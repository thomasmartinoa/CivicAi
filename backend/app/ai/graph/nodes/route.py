"""Pick the owning department and the best-placed contractor.

Two v1 defects fixed structurally:

- The department comes from `Department.categories`, the JSON column v1
  declared, seeded, and then ignored in favour of a hardcoded dict that drifted
  until CONSTRUCTION and SEWAGE pointed at departments that did not exist.
- Contractor scoring lives here once. v1 copy-pasted the identical loop into
  three files, so changing a weight meant remembering all three.

From Phase 2b the routing justification cites the department's SOP and the
contractor scoring policy, so an officer can see which document a decision
rests on.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.retrieval import retrieve
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


def _justify(department, contractor, category: Category, district: str | None,
             evidence: list, contractor_score: float = 0.0) -> str:
    """One sentence per decision, each citing the evidence chunk it rests on.

    Citation numbers follow the order of `evidence`, which is the order the
    chunks are returned into state, which is the order format_evidence()
    numbers them — so the UI and the model agree on what [1] means.
    """
    cite = {c.source: f" [{i}]" for i, c in enumerate(evidence, start=1)}
    sop_ref = next((ref for src, ref in cite.items() if src.startswith("sop_")), "")
    policy_ref = cite.get("contractor_scoring.md", "")

    owner = department.name if department else "no seeded department"
    parts = [f"{owner} owns {category.value}{sop_ref}."]
    if contractor:
        reasons = []
        if contractor.specializations and category.value in contractor.specializations:
            reasons.append("specialist")
        reasons.append(f"rating {contractor.rating or 0.0:.1f}")
        reasons.append(f"workload {contractor.active_workload or 0}")
        if district and contractor.zone and contractor.zone.lower() == district.lower():
            reasons.append("zone match")
        parts.append(
            f"{contractor.name} scored {contractor_score:.0f} under the contractor "
            f"scoring policy{policy_ref} ({', '.join(reasons)})."
        )
    else:
        parts.append("No contractor is registered for this tenant.")
    return " ".join(parts)


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
            "evidence": [],
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
        contractor_score = score_contractor(contractor, category, district) if contractor else 0.0
    finally:
        session.close()

    deps = deps_from_config(config)
    # Two targeted searches rather than one broad one: the SOP is filtered to
    # this category, and the scoring policy has no category at all.
    sop = retrieve(
        deps.policy_retriever,
        f"which department owns {category.value} complaints and who escalates",
        node="route", k=1, filters={"doc_type": "sop", "category": category.value},
    )
    policy = retrieve(
        deps.policy_retriever,
        "how contractors are scored: specialisation, rating, workload, zone",
        node="route", k=1, filters={"doc_type": "contractor_scoring"},
    )
    evidence = sop.chunks + policy.chunks
    # One error entry, not two: both searches fail for the same reason.
    errors = [sop.error] if sop.error else ([policy.error] if policy.error else [])

    justification = _justify(department, contractor, category, district, evidence, contractor_score)
    routing = RoutingDecision(
        department_name=department.name if department else "General Administration",
        department_id=department.id if department else None,
        contractor_id=contractor.id if contractor else None,
        contractor_name=contractor.name if contractor else None,
        jurisdiction_level=_jurisdiction(state),
        justification=justification,
    )
    return {
        "routing": routing,
        "evidence": evidence,
        "errors": errors,
        "decision_log": [NodeDecision(
            node="route",
            summary=f"{routing.department_name} / {routing.contractor_name or 'no contractor'}",
        )],
    }
