"""The officer agent's tools.

Two properties hold for every tool in this module, and both are enforced by the
*shape* of the code rather than by asking the model to behave.

**No tool takes a tenant.** `build_officer_tools` closes over the authenticated
officer's `tenant_id` and each tool reads it from that closure. There is no parameter
an LLM could fill with the wrong value. This matters more than it may look: the
agent's context contains complaint text written by members of the public, and Phase 3
*measured* that 1 in 6 prompt-injection items still moves a risk band — steering this
model with citizen-supplied text is demonstrated, not hypothetical. A signature that
cannot express the wrong tenant beats a prompt that asks nicely.
`tests/test_import_rules.py` fails if a `tenant_id` parameter appears here.

**No tool changes anything.** The spec defers human-in-the-loop `interrupt()` approval
to Phase 7, so there is no mechanism by which an officer confirms an agent's action
before it happens. Until there is, an LLM does not get to move a work order. An
officer who wants a change uses the PATCH endpoints, where the transition is
allow-listed and their id lands on the row.

**Nothing here computes a number.** SLA bands come from `services/sla.py`, contractor
scores from `route.score_contractor`, statistics from `services/analytics.py`. An
agent that recomputed any of them would drift from the system it is describing, and
the officer would be holding two answers with no way to tell which was real.

Tools return small plain dicts, never ORM objects: the result is serialised into a
prompt, and a lazy relationship touched after its session closed raises there instead
of here.
"""

import logging
from collections.abc import Callable

from langchain_core.tools import StructuredTool

from app.ai.graph.retrieval import DEFAULT_FETCH_K

logger = logging.getLogger(__name__)

MAX_ROWS = 25
"""Hard cap on any list a tool returns. The model may ask for fewer; it cannot ask for
more. A tool that returned a tenant's whole complaint table would blow the context
window and the quota in one call."""

NO_RESULT = "No matching records."
"""Returned as a message rather than raised. A tool that raises ends the agent's turn,
so "nothing matched" has to be an answer the model can reason about — otherwise an
empty result looks like a broken system."""


def _citation(hit) -> str:
    """`source › headers`, the same shape the graph nodes record in `evidence`."""
    headers = hit.chunk.metadata.get("headers") or []
    trail = " › ".join(str(h) for h in headers)
    return f"{hit.chunk.source} › {trail}" if trail else hit.chunk.source


def build_officer_tools(
    session_factory: Callable,
    *,
    tenant_id: str,
    policy_retriever=None,
) -> list[StructuredTool]:
    """The tool list for one officer's conversation.

    `tenant_id` is a keyword of *this* function and of none of the tools it returns.
    That asymmetry is the whole security model.

    Each tool opens and closes its own session. The alternative — one session for the
    conversation — would hold a connection open across model calls that take seconds
    each at the free tier's rate limit.
    """

    def _session():
        return session_factory()

    # ── policy ──────────────────────────────────────────────────────────────

    def search_policy(query: str, k: int = 4) -> dict:
        """Search the municipal corpus: SOPs, the rate card, escalation policy.

        Returns passages with citations. Use this for any question about what the
        rules say, rather than answering from memory.
        """
        if policy_retriever is None:
            # A soft dependency everywhere else in this codebase, and the same here:
            # the agent can still answer from the database.
            return {"error": "The policy index is unavailable.", "passages": []}
        try:
            # The retriever protocol is keyword-only in all three arguments — see
            # GraphDeps.policy_retriever. Calling it with only `k` raises a
            # TypeError, which a loose test fake will happily hide: this module's
            # first live run did exactly that.
            hits = policy_retriever.search(
                query, k=min(k, 10), fetch_k=DEFAULT_FETCH_K, filters=None,
            )
        except Exception as exc:  # noqa: BLE001 - a dead index must not end the turn
            logger.warning("policy search failed: %s", exc)
            return {"error": "The policy index could not be searched.", "passages": []}
        return {
            "passages": [
                {"citation": _citation(h), "text": h.chunk.text[:600], "score": round(h.score, 4)}
                for h in hits
            ]
        }

    # ── complaints ──────────────────────────────────────────────────────────

    def find_complaints(
        category: str | None = None,
        status: str | None = None,
        district: str | None = None,
        risk_level: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Find complaints in this department, newest first.

        All filters are optional. Categories are upper snake case, for example
        ROADS or PUBLIC_SPACES.
        """
        from app.db.models.complaint import Complaint

        session = _session()
        try:
            query = session.query(Complaint).filter(Complaint.tenant_id == tenant_id)
            if category:
                query = query.filter(Complaint.category == category.upper())
            if status:
                query = query.filter(Complaint.status == status.lower())
            if district:
                query = query.filter(Complaint.district.ilike(f"%{district}%"))
            if risk_level:
                query = query.filter(Complaint.risk_level == risk_level.lower())
            rows = (query.order_by(Complaint.created_at.desc())
                    .limit(max(1, min(limit, MAX_ROWS))).all())
            if not rows:
                return {"message": NO_RESULT, "complaints": []}
            return {"complaints": [
                {
                    "tracking_id": c.tracking_id,
                    "status": c.status,
                    "category": c.category,
                    "risk_level": c.risk_level,
                    "priority_score": c.priority_score,
                    "district": c.district,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "summary": (c.description or "")[:200],
                }
                for c in rows
            ]}
        finally:
            session.close()

    def get_complaint(tracking_id: str) -> dict:
        """One complaint in full, including why the pipeline routed it where it did
        and which documents it cited.

        Prefer this over re-deciding anything yourself: the stored justification is
        what the department actually acted on.
        """
        from app.db.models.complaint import Complaint

        session = _session()
        try:
            complaint = (session.query(Complaint)
                         .filter(Complaint.tracking_id == tracking_id.strip().upper(),
                                 Complaint.tenant_id == tenant_id)
                         .one_or_none())
            if complaint is None:
                # A message, not an exception: the officer may have misread an id,
                # and the agent should say so rather than crash the turn.
                return {"message": f"No complaint {tracking_id!r} in this department."}
            order = complaint.work_order
            return {
                "tracking_id": complaint.tracking_id,
                "status": complaint.status,
                "category": complaint.category,
                "subcategory": complaint.subcategory,
                "risk_level": complaint.risk_level,
                "priority_score": complaint.priority_score,
                "district": complaint.district,
                "ward": complaint.ward,
                "description": complaint.description,
                "terminal_reason": complaint.terminal_reason,
                "routing_justification": complaint.routing_justification,
                "citations": [
                    e.get("source") and f"{e.get('source')} › {' › '.join(e.get('headers') or [])}"
                    for e in (complaint.evidence or [])
                ],
                "reopen_count": complaint.reopen_count,
                "work_order": None if order is None else {
                    "status": order.status,
                    "sla_hours": order.sla_hours,
                    "sla_deadline": order.sla_deadline.isoformat() if order.sla_deadline else None,
                    "contractor": order.contractor.name if order.contractor else None,
                    "estimated_cost": order.estimated_cost,
                },
            }
        finally:
            session.close()

    # ── operations ──────────────────────────────────────────────────────────

    def work_orders_at_risk() -> dict:
        """Open work orders that are close to breaching their SLA, or have breached.

        The bands are the same ones the escalation emails use, so this cannot
        disagree with what a contractor was told.
        """
        from app.db.base import utcnow
        from app.constants import WORK_ORDER_CLOSED
        from app.db.models.workflow import WorkOrder
        from app.services.sla import URGENT_AT, WARNING_AT, elapsed_fraction

        session = _session()
        try:
            orders = (session.query(WorkOrder)
                      .filter(WorkOrder.tenant_id == tenant_id,
                              WorkOrder.status.notin_(WORK_ORDER_CLOSED),
                              WorkOrder.sla_deadline.isnot(None))
                      .all())
            now = utcnow()
            at_risk = []
            for order in orders:
                fraction = elapsed_fraction(order, now)
                if fraction >= 1.0:
                    state = "breached"
                elif fraction >= URGENT_AT:
                    state = "urgent"
                elif fraction >= WARNING_AT:
                    state = "warning"
                else:
                    continue
                at_risk.append({
                    "tracking_id": order.complaint.tracking_id if order.complaint else None,
                    "category": order.complaint.category if order.complaint else None,
                    "sla_state": state,
                    "elapsed_fraction": round(fraction, 3),
                    "sla_deadline": order.sla_deadline.isoformat(),
                    "contractor": order.contractor.name if order.contractor else None,
                })
            if not at_risk:
                return {"message": "Nothing is at risk right now.", "work_orders": []}
            at_risk.sort(key=lambda row: -row["elapsed_fraction"])
            return {"work_orders": at_risk[:MAX_ROWS]}
        finally:
            session.close()

    def contractor_options(category: str, district: str | None = None) -> dict:
        """Contractors ranked for a category, best first.

        Uses the pipeline's own scoring, so the order here is the order `route`
        would have chosen. The score is not a percentage; only the ranking and the
        stated reasons are meaningful.
        """
        from app.ai.graph.nodes.route import score_contractor
        from app.constants import Category
        from app.db.models.core import Contractor

        try:
            parsed = Category(category.upper())
        except ValueError:
            return {"error": f"{category!r} is not a category.",
                    "valid": [c.value for c in Category]}

        session = _session()
        try:
            contractors = (session.query(Contractor)
                           .filter(Contractor.tenant_id == tenant_id).all())
            if not contractors:
                return {"message": NO_RESULT, "contractors": []}
            scored = sorted(
                ((score_contractor(c, parsed, district), c) for c in contractors),
                key=lambda pair: -pair[0],
            )
            return {"contractors": [
                {
                    "name": c.name,
                    "score": round(score, 1),
                    "specialist": bool(c.specializations and parsed.value in c.specializations),
                    "rating": c.rating,
                    "active_workload": c.active_workload,
                    "zone": c.zone,
                }
                for score, c in scored[:MAX_ROWS]
            ]}
        finally:
            session.close()

    def tenant_statistics() -> dict:
        """Counts, median resolution time and SLA compliance for this department.

        A null means not measured rather than zero — median resolution over nothing
        resolved is not 0 hours. Say "no data" rather than quoting a zero.
        """
        from app.services.analytics import complaint_counts, resolution_stats, sla_compliance

        session = _session()
        try:
            counts = complaint_counts(session, tenant_id=tenant_id)
            resolution = resolution_stats(session, tenant_id=tenant_id)
            compliance = sla_compliance(session, tenant_id=tenant_id)
            return {
                "total_complaints": counts.total,
                "by_status": counts.by_status,
                "by_category": counts.by_category,
                "by_risk_level": counts.by_risk_level,
                "completed_work_orders": resolution.completed,
                "median_resolution_hours": resolution.median_hours,
                "sla_measured": compliance.measured,
                "sla_breached": compliance.breached,
                "sla_compliance_rate": compliance.rate,
            }
        finally:
            session.close()

    return [
        StructuredTool.from_function(func=fn, name=fn.__name__, description=fn.__doc__)
        for fn in (search_policy, find_complaints, get_complaint,
                   work_orders_at_risk, contractor_options, tenant_statistics)
    ]


OFFICER_TOOL_NAMES = (
    "search_policy", "find_complaints", "get_complaint",
    "work_orders_at_risk", "contractor_options", "tenant_statistics",
)
