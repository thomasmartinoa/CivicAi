"""Group complaints that describe the same problem in the same place.

v1 bucketed on `f"{category}|{round(lat, 2)}|{round(lng, 2)}"`: two reports of
one collapsed road grouped only if the classifier happened to give them the
same label *and* their coordinates rounded into the same ~1 km cell. Two
complaints 200 m apart either shared a cell or straddled an edge, and nothing
about the wording mattered.

Here distance is continuous (haversine, a radius in kilometres) and matching is
on meaning (cosine over the same 768-dimensional embeddings the RAG stack
uses). The category is deliberately *not* part of the match — "the contractor
dug up MG Road" and "the MG Road surface caved in" are one job for one crew
however they were classified — but the cluster inherits its lead's category, so
the grouped work order still has exactly one department to route to.

This module is the pure half: lists in, clusters out, no database and no model.
The hourly job that reads complaints and writes work orders is built on top of
it.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

import numpy as np

from app.ai.rag.embeddings import Embedder
from app.config import settings

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Candidate:
    """One complaint, reduced to what clustering needs.

    A plain dataclass rather than the ORM object so the algorithm can be tested
    without a database, and so nothing here can lazily load a relationship.
    """

    id: str
    text: str
    coords: tuple[float, float]
    priority: int
    created_at: datetime
    category: str
    district: str | None = None
    """Only used for contractor scoring, so it is optional for the pure
    clustering path that never looks at it."""


@dataclass
class Cluster:
    lead: Candidate
    members: list[Candidate]

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def ids(self) -> list[str]:
        return [m.id for m in self.members]

    @property
    def category(self) -> str:
        """The lead's category: a cluster may span categories, but a work order
        routes to one department."""
        return self.lead.category


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres.

    Not Euclidean on raw degrees: a degree of longitude is ~111 km at the
    equator and ~0 at the poles, so a plain subtraction would make the radius
    mean different things in different cities.
    """
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, h)))


def cosine(u: np.ndarray, v: np.ndarray) -> float:
    """Cosine similarity. Normalises even though the embedders return unit
    vectors — a future embedder that does not would otherwise skew every
    comparison silently."""
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0 or nv == 0:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))


def cluster_candidates(
    candidates: list[Candidate],
    *,
    embedder: Embedder,
    radius_km: float,
    threshold: float,
    min_size: int,
) -> list[Cluster]:
    """Group candidates by similarity within a radius. Greedy, deterministic.

    The walk is ordered by descending priority, then oldest first, then id, so
    the most urgent report leads its cluster and the same input always produces
    the same output whatever order it arrives in.

    A lead claims every unclaimed candidate that is both within `radius_km` and
    at or above `threshold` cosine. If the group does not reach `min_size` the
    claims are released, so those candidates remain available to a later lead —
    a pair is not a cluster, but it must not be consumed as one either.
    """
    if len(candidates) < max(2, min_size):
        # Nothing can group, so do not pay for embeddings at all. The hourly
        # job runs against a real embedding API.
        return []

    ordered = sorted(candidates, key=lambda c: (-c.priority, c.created_at, c.id))
    vectors = np.asarray(embedder.embed_documents([c.text for c in ordered]), dtype="float32")

    claimed: set[str] = set()
    clusters: list[Cluster] = []

    for i, lead in enumerate(ordered):
        if lead.id in claimed:
            continue
        members = [lead]
        for j, other in enumerate(ordered):
            if i == j or other.id in claimed:
                continue
            if haversine_km(lead.coords, other.coords) > radius_km:
                continue
            if cosine(vectors[i], vectors[j]) < threshold:
                continue
            members.append(other)
        if len(members) < min_size:
            continue  # nothing claimed yet, so the members stay available
        claimed.update(m.id for m in members)
        clusters.append(Cluster(lead=lead, members=members))

    return clusters


# ── the hourly job ──────────────────────────────────────────────────────────

# A complaint is worth clustering once the pipeline has classified it and until
# it is finished. The vocabulary comes from `_status_for` in ai/graph/runner.py:
# "submitted" has no category yet, "rejected" and "failed" have no work to do,
# and "resolved" is done.
CLUSTERABLE_STATUSES = ("processed", "assigned")


@dataclass
class ClusterTick:
    clusters: int = 0
    complaints: int = 0


def open_candidates(session, *, tenant_id: str) -> list[Candidate]:
    """Unclustered, classified, located, unfinished complaints for one tenant.

    Coordinates are required rather than defaulted. v1 wrote
    `round(complaint.latitude or 0, 2)`, which put every complaint without a
    location in one bucket at (0, 0) — in the Gulf of Guinea — and clustered
    them with each other.
    """
    from app.db.models.complaint import Complaint

    rows = (
        session.query(Complaint)
        .filter(
            Complaint.tenant_id == tenant_id,
            Complaint.cluster_id.is_(None),
            Complaint.status.in_(CLUSTERABLE_STATUSES),
            Complaint.category.isnot(None),
            Complaint.latitude.isnot(None),
            Complaint.longitude.isnot(None),
        )
        .all()
    )
    return [
        Candidate(id=r.id, text=r.description, coords=(r.latitude, r.longitude),
                  priority=r.priority_score or 0, created_at=r.created_at,
                  category=r.category, district=r.district)
        for r in rows
    ]


def cluster_work_order(session, complaint):
    """The work order covering this complaint.

    A member of a cluster has none of its own: the grouped order hangs off the
    lead, because work_orders.complaint_id is unique. Every caller that wants
    "the order for this complaint" goes through here rather than re-deriving it.
    """
    from app.db.models.workflow import WorkOrder

    if complaint.cluster_id and complaint.cluster_id != complaint.id:
        return session.query(WorkOrder).filter_by(complaint_id=complaint.cluster_id).one_or_none()
    return session.query(WorkOrder).filter_by(complaint_id=complaint.id).one_or_none()


def _worst_risk(members, session) -> str:
    """The most urgent band in the cluster. One trip serves every site, so the
    window is the shortest any member is owed."""
    from app.constants import RiskLevel
    from app.db.models.complaint import Complaint

    order = [RiskLevel.CRITICAL.value, RiskLevel.HIGH.value, RiskLevel.MEDIUM.value, RiskLevel.LOW.value]
    levels = [
        c.risk_level for c in session.query(Complaint).filter(
            Complaint.id.in_([m.id for m in members])
        ).all() if c.risk_level in order
    ]
    return min(levels, key=order.index) if levels else RiskLevel.MEDIUM.value


def _cluster_cost(cluster, *, cost_chain, retriever, risk_level: str) -> tuple[float | None, str, str]:
    """Price the grouped job from the rate card's own grouped-work rule.

    v1 used `base * count * 0.7` in Python. The discount is a municipal rule, so
    it is retrieved and cited. A failure here is soft: the crew still needs the
    job, so the cost is honestly None and cost_basis says why.
    """
    from app.ai.graph.retrieval import format_evidence, retrieve

    rates = retrieve(retriever, f"unit rates and grouped work at multiple sites for {cluster.category}",
                     node="cluster_detection", k=4, filters={"doc_type": "rate_card"})
    if cost_chain is None:
        return None, "estimate unavailable: no cost chain configured", "To be determined on site inspection"
    try:
        estimate = cost_chain.invoke({
            "category": cluster.category,
            "risk_level": risk_level,
            "site_count": cluster.size,
            "descriptions": "\n".join(f"- {m.text}" for m in cluster.members),
            "evidence": format_evidence(rates.chunks),
        })
        return estimate.estimated_cost, estimate.cost_basis, estimate.materials
    except Exception as exc:
        logger.warning("cluster cost estimate failed for lead %s", cluster.lead.id, exc_info=True)
        return None, f"estimate unavailable: {exc}", "To be determined on site inspection"


def _grouped_order(session, cluster, *, tenant_id, risk_level, sla_hours, cost):
    """Create or update the one work order covering the cluster.

    Update rather than insert when the lead already has an order:
    work_orders.complaint_id is unique, so a blind insert would raise, and
    deleting the existing one would discard work already dispatched.
    """
    from app.ai.graph.nodes.route import score_contractor
    from app.constants import Category
    from app.db.base import utcnow
    from app.db.models.core import Contractor
    from app.db.models.workflow import WorkOrder

    estimated_cost, cost_basis, materials = cost
    contractors = session.query(Contractor).filter(Contractor.tenant_id == tenant_id).all()
    contractor = None
    if contractors and cluster.category in {c.value for c in Category}:
        category = Category(cluster.category)
        contractor = max(contractors, key=lambda c: score_contractor(c, category, cluster.lead.district))

    order = session.query(WorkOrder).filter_by(complaint_id=cluster.lead.id).one_or_none()
    if order is None:
        order = WorkOrder(complaint_id=cluster.lead.id, tenant_id=tenant_id)
        session.add(order)
    order.is_cluster = True
    order.cluster_size = cluster.size
    order.status = "assigned"
    order.sla_hours = sla_hours
    order.sla_deadline = utcnow() + timedelta(hours=sla_hours)
    order.estimated_cost = estimated_cost
    order.cost_basis = cost_basis
    order.materials = materials
    order.notes = (f"Grouped work order covering {cluster.size} nearby reports "
                   f"({', '.join(cluster.ids)}).")
    if contractor is not None:
        order.contractor_id = contractor.id
        contractor.active_workload = (contractor.active_workload or 0) + 1
    return order


def detect_clusters(
    *,
    session_factory: Callable,
    embedder: Embedder | None = None,
    cost_chain=None,
    retriever=None,
    radius_km: float | None = None,
    threshold: float | None = None,
    min_size: int | None = None,
) -> ClusterTick:
    """One pass, per tenant, over everything not yet clustered.

    Idempotent through `Complaint.cluster_id`: a clustered complaint is not a
    candidate again, so running this every hour groups each report at most once.
    """
    from app.db.models.core import Tenant

    radius_km = settings.cluster_radius_km if radius_km is None else radius_km
    threshold = settings.cluster_similarity_threshold if threshold is None else threshold
    min_size = settings.cluster_min_size if min_size is None else min_size

    tick = ClusterTick()
    session = session_factory()
    try:
        if embedder is None:
            from app.ai.rag.embeddings import build_embedder

            embedder = build_embedder()

        for tenant_id, in session.query(Tenant.id).all():
            candidates = open_candidates(session, tenant_id=tenant_id)
            clusters = cluster_candidates(candidates, embedder=embedder, radius_km=radius_km,
                                          threshold=threshold, min_size=min_size)
            for cluster in clusters:
                risk_level = _worst_risk(cluster.members, session)
                _mark_members(session, cluster)
                _grouped_order(
                    session, cluster, tenant_id=tenant_id, risk_level=risk_level,
                    sla_hours=_sla_hours_for_cluster(session, tenant_id, risk_level),
                    cost=_cluster_cost(cluster, cost_chain=cost_chain, retriever=retriever,
                                       risk_level=risk_level),
                )
                tick.clusters += 1
                tick.complaints += cluster.size
            session.commit()
        if tick.clusters:
            logger.info("cluster detection: %s", tick)
        return tick
    finally:
        session.close()


def _mark_members(session, cluster) -> None:
    from app.db.models.complaint import Complaint

    for member in session.query(Complaint).filter(Complaint.id.in_(cluster.ids)).all():
        member.cluster_id = cluster.lead.id


def _sla_hours_for_cluster(session, tenant_id: str, risk_level: str) -> int:
    from app.constants import RiskLevel
    from app.db.models.core import Tenant
    from app.services.tenancy import sla_hours_for

    return sla_hours_for(session.get(Tenant, tenant_id), RiskLevel(risk_level))
