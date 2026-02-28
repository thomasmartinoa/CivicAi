from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models.complaint import Complaint

router = APIRouter(prefix="/public", tags=["public"])


from app.utils.locations import STATE_DISTRICT_MAP

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

    if district:
        # Match district column OR address text
        query = query.filter(
            (Complaint.district == district) |
            (Complaint.address.ilike(f"%{district}%"))
        )
    elif state:
        # Match state name in address text (works even when district column is NULL)
        query = query.filter(Complaint.address.ilike(f"%{state}%"))

    total = query.count()
    resolved = query.filter(Complaint.status.in_(["resolved", "closed"])).count()
    resolution_rate = (resolved / total * 100) if total > 0 else 0

    by_category = dict(
        query.with_entities(Complaint.category, func.count(Complaint.id))
        .filter(Complaint.category.isnot(None)).group_by(Complaint.category).all()
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
        # Convert absolute file path to relative URL (just the filename)
        media_url = None
        if c.media:
            import os as _os
            media_url = "media/" + _os.path.basename(c.media[0].file_path)
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

    by_status = dict(
        query.with_entities(Complaint.status, func.count(Complaint.id)).group_by(Complaint.status).all()
    )

    return {
        "total_complaints": total, "resolved_complaints": resolved,
        "resolution_rate": round(resolution_rate, 1),
        "by_category": by_category, "by_status": by_status, "heatmap_data": heatmap,
        "recent_complaints": recent_complaints,
    }
