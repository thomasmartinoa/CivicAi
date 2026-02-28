from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models.complaint import Complaint

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/dashboard")
async def public_dashboard(
    tenant_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Complaint)
    if tenant_id:
        query = query.filter(Complaint.tenant_id == tenant_id)

    if category:
        query = query.filter(Complaint.category == category)

    # Filter by state using the stored state field (from geocoding)
    if state:
        query = query.filter(Complaint.state == state)

    # Filter by district (fuzzy match since Nominatim names differ from official names)
    if district:
        query = query.filter(
            Complaint.district.ilike(f"%{district}%") |
            Complaint.address.ilike(f"%{district}%")
        )

    total = query.count()
    resolved = query.filter(Complaint.status.in_(["resolved", "closed"])).count()
    resolution_rate = (resolved / total * 100) if total > 0 else 0

    by_category = dict(
        query.with_entities(Complaint.category, func.count(Complaint.id))
        .filter(Complaint.category.isnot(None)).group_by(Complaint.category).all()
    )

    by_status = dict(
        query.with_entities(Complaint.status, func.count(Complaint.id)).group_by(Complaint.status).all()
    )

    # Calculate colors based on risk_level/status
    RISK_COLORS = {
        "critical": "#ef4444",
        "high": "#f97316",
        "medium": "#eab308",
        "low": "#22c55e",
    }
    heatmap = []
    for c in query.filter(Complaint.latitude.isnot(None), Complaint.longitude.isnot(None)).limit(500).all():
        if c.status in ["resolved", "closed"]:
            color = "#22c55e"
        else:
            color = RISK_COLORS.get(c.risk_level or "medium", "#eab308")
        heatmap.append({
            "lat": c.latitude,
            "lng": c.longitude,
            "category": c.category,
            "status": c.status,
            "risk_level": c.risk_level,
            "color": color,
        })

    recent_complaints = []
    for c in query.order_by(Complaint.created_at.desc()).options(joinedload(Complaint.media)).limit(50).all():
        media_url = None
        if c.media:
            # Find first image media, prefer image type
            for m in c.media:
                if m.media_type == 'image':
                    media_url = m.file_path
                    break
            if not media_url:
                media_url = c.media[0].file_path
        recent_complaints.append({
            "id": c.id,
            "description": c.description,
            "category": c.category,
            "status": c.status,
            "address": c.address,
            "created_at": c.created_at.isoformat(),
            "risk_level": c.risk_level,
            "media_url": media_url,
            "citizen_name": c.citizen_name
        })

    return {
        "total_complaints": total, "resolved_complaints": resolved,
        "resolution_rate": round(resolution_rate, 1),
        "by_category": by_category, "by_status": by_status, "heatmap_data": heatmap,
        "recent_complaints": recent_complaints,
    }
