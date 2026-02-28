"""
ClusterDetectionAgent — groups related complaints by category + proximity,
creates a grouped work order covering all complaints in the cluster.
Runs on a schedule (e.g. every hour or daily).
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session


CLUSTER_THRESHOLD = 2          # min complaints to form a cluster
GEO_PRECISION = 2              # decimal places for lat/lng bucketing (~1 km grid)
LOOKBACK_DAYS = 7              # only look at recent unresolved complaints


async def run_cluster_detection(db: Session):
    from app.models.complaint import Complaint
    from app.models.work_order import WorkOrder

    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    open_complaints = db.query(Complaint).filter(
        Complaint.status.not_in(["resolved", "closed", "grouped"]),
        Complaint.created_at >= since,
        Complaint.category.isnot(None),
    ).all()

    # Bucket complaints by category + geo cell (fall back to district/ward if no GPS)
    buckets: dict[str, list[Complaint]] = {}
    for complaint in open_complaints:
        if complaint.latitude and complaint.longitude and not (complaint.latitude == 0 and complaint.longitude == 0):
            lat = round(complaint.latitude, GEO_PRECISION)
            lng = round(complaint.longitude, GEO_PRECISION)
            geo_key = f"{lat}|{lng}"
        else:
            # Fall back to district or ward for grouping
            geo_key = complaint.district or complaint.ward or "unknown_area"
        key = f"{complaint.category}|{geo_key}"
        buckets.setdefault(key, []).append(complaint)

    clusters_created = 0
    for key, complaints in buckets.items():
        if len(complaints) < CLUSTER_THRESHOLD:
            continue

        # Check if a cluster work order already exists for this group
        complaint_ids = [c.id for c in complaints]
        existing_cluster_wo = db.query(WorkOrder).filter(
            WorkOrder.complaint_id.in_(complaint_ids),
            WorkOrder.notes.like("%[CLUSTER]%"),
        ).first()
        if existing_cluster_wo:
            continue  # already handled

        category = complaints[0].category
        district = complaints[0].district or "unknown"
        descriptions = "; ".join([c.description[:80] for c in complaints[:5]])
        cluster_summary = (
            f"[CLUSTER] {len(complaints)} related {category} complaints detected in "
            f"{district} district. Auto-generated grouped work order. "
            f"Complaint IDs: {', '.join(complaint_ids[:10])}. "
            f"Sample descriptions: {descriptions}"
        )

        # Find best contractor for this cluster
        contractor = _find_cluster_contractor(db, complaints[0].tenant_id, category, district)

        # Create a single work order on the highest-priority complaint
        anchor = max(complaints, key=lambda c: c.priority_score or 0)

        from app.models.work_order import WorkOrder as WO
        wo = WO(
            complaint_id=anchor.id,
            tenant_id=anchor.tenant_id,
            contractor_id=str(contractor.id) if contractor else None,
            status="assigned" if contractor else "created",
            sla_deadline=datetime.now(timezone.utc) + timedelta(hours=48),
            estimated_cost=_estimate_cluster_cost(category, len(complaints)),
            notes=cluster_summary,
        )
        db.add(wo)

        # Mark all complaints in cluster as "grouped"
        for c in complaints:
            if c.status not in ("assigned", "in_progress", "resolved", "closed"):
                c.status = "grouped"

        if contractor:
            from app.models.contractor import Contractor
            c = db.query(Contractor).filter(Contractor.id == contractor.id).first()
            if c:
                c.active_workload = (c.active_workload or 0) + 1

        db.commit()
        clusters_created += 1
        print(f"[ClusterAgent] Created cluster work order for {len(complaints)} {category} complaints in {district}")

    print(f"[ClusterAgent] Done. Clusters created: {clusters_created}")
    return clusters_created


def _find_cluster_contractor(db, tenant_id, category, district):
    from app.models.contractor import Contractor
    contractors = db.query(Contractor).filter(
        Contractor.tenant_id == tenant_id
    ).all()
    if not contractors:
        return None
    scored = []
    for c in contractors:
        score = 0.0
        if c.specializations and category in c.specializations:
            score += 40
        score += (c.rating or 0) * 6
        score += max(0, 20 - (c.active_workload or 0) * 2)
        if c.zone and c.zone.lower() == (district or "").lower():
            score += 10
        scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored else None


def _estimate_cluster_cost(category: str, count: int) -> float:
    base = {
        "ROADS": 5000, "ELECTRICITY": 3000, "WATER": 4000, "SANITATION": 2000,
        "PUBLIC_SPACES": 3000, "SEWAGE": 5000, "FLOODING": 10000,
    }.get(category, 4000)
    return base * count * 0.7  # 30% discount for bulk work
