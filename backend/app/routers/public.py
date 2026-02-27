from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models.complaint import Complaint

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/dashboard")
async def public_dashboard(tenant_id: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Complaint)
    if tenant_id:
        query = query.filter(Complaint.tenant_id == tenant_id)

    total = query.count()
    resolved = query.filter(Complaint.status.in_(["resolved", "closed"])).count()
    resolution_rate = (resolved / total * 100) if total > 0 else 0

    by_category = dict(
        query.with_entities(Complaint.category, func.count(Complaint.id))
        .filter(Complaint.category.isnot(None)).group_by(Complaint.category).all()
    )
    heatmap = [
        {"lat": c.latitude, "lng": c.longitude, "category": c.category, "status": c.status}
        for c in query.filter(Complaint.latitude.isnot(None), Complaint.longitude.isnot(None)).limit(500).all()
    ]
    by_status = dict(
        query.with_entities(Complaint.status, func.count(Complaint.id)).group_by(Complaint.status).all()
    )

    return {
        "total_complaints": total, "resolved_complaints": resolved,
        "resolution_rate": round(resolution_rate, 1),
        "by_category": by_category, "by_status": by_status, "heatmap_data": heatmap,
    }
