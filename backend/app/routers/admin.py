from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.complaint import Complaint
from app.models.work_order import WorkOrder
from app.models.contractor import Contractor
from app.models.user import User
from app.schemas.work_order import WorkOrderUpdate
from app.utils.auth import require_officer_or_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/complaints")
async def list_complaints(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Complaint)
    if user.tenant_id:
        query = query.filter(Complaint.tenant_id == user.tenant_id)
    if status:
        query = query.filter(Complaint.status == status)
    if category:
        query = query.filter(Complaint.category == category)
    if risk_level:
        query = query.filter(Complaint.risk_level == risk_level)

    total = query.count()
    complaints = query.order_by(Complaint.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "complaints": [
            {
                "id": str(c.id), "tracking_id": c.tracking_id, "status": c.status,
                "description": c.description, "category": c.category,
                "subcategory": c.subcategory, "priority_score": c.priority_score,
                "risk_level": c.risk_level, "address": c.address,
                "citizen_email": c.citizen_email,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in complaints
        ],
        "total": total,
    }


@router.patch("/complaints/{complaint_id}")
async def update_complaint(
    complaint_id: str, status: Optional[str] = None, contractor_id: Optional[str] = None,
    user: User = Depends(require_officer_or_admin), db: Session = Depends(get_db),
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if status:
        complaint.status = status
    if contractor_id:
        wo = db.query(WorkOrder).filter(WorkOrder.complaint_id == complaint.id).first()
        if wo:
            wo.contractor_id = contractor_id
            wo.officer_id = user.id
    db.commit()
    return {"message": "Complaint updated"}


@router.get("/work-orders")
async def list_work_orders(
    status: Optional[str] = Query(None),
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    query = db.query(WorkOrder)
    if user.tenant_id:
        query = query.filter(WorkOrder.tenant_id == user.tenant_id)
    if status:
        query = query.filter(WorkOrder.status == status)
    orders = query.order_by(WorkOrder.created_at.desc()).all()
    return {
        "work_orders": [
            {
                "id": str(wo.id), "complaint_id": str(wo.complaint_id),
                "contractor_id": str(wo.contractor_id) if wo.contractor_id else None,
                "status": wo.status,
                "sla_deadline": wo.sla_deadline.isoformat() if wo.sla_deadline else None,
                "estimated_cost": wo.estimated_cost, "notes": wo.notes,
                "created_at": wo.created_at.isoformat() if wo.created_at else None,
            }
            for wo in orders
        ]
    }


@router.patch("/work-orders/{work_order_id}")
async def update_work_order(
    work_order_id: str, data: WorkOrderUpdate,
    user: User = Depends(require_officer_or_admin), db: Session = Depends(get_db),
):
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    prev_status = wo.status
    prev_contractor_id = wo.contractor_id

    if data.status:
        wo.status = data.status
        if data.status == "completed":
            from datetime import datetime, timezone
            wo.completed_at = datetime.now(timezone.utc)
        # Sync contractor active_workload
        active_statuses = {"created", "assigned", "in_progress"}
        was_active = prev_status in active_statuses
        is_active = data.status in active_statuses
        if was_active and not is_active and prev_contractor_id:
            contractor = db.query(Contractor).filter(Contractor.id == prev_contractor_id).first()
            if contractor and contractor.active_workload > 0:
                contractor.active_workload -= 1
        elif not was_active and is_active and (data.contractor_id or wo.contractor_id):
            cid = data.contractor_id or wo.contractor_id
            contractor = db.query(Contractor).filter(Contractor.id == cid).first()
            if contractor:
                contractor.active_workload += 1

    if data.notes:
        wo.notes = data.notes
    if data.contractor_id:
        # Transferring contractor — decrement old, increment new
        if prev_contractor_id and prev_contractor_id != data.contractor_id and wo.status in {"assigned", "in_progress"}:
            old_c = db.query(Contractor).filter(Contractor.id == prev_contractor_id).first()
            if old_c and old_c.active_workload > 0:
                old_c.active_workload -= 1
            new_c = db.query(Contractor).filter(Contractor.id == data.contractor_id).first()
            if new_c:
                new_c.active_workload += 1
        wo.contractor_id = data.contractor_id
        wo.officer_id = user.id
    db.commit()
    return {"message": "Work order updated"}


@router.get("/analytics")
async def get_analytics(user: User = Depends(require_officer_or_admin), db: Session = Depends(get_db)):
    query = db.query(Complaint)
    if user.tenant_id:
        query = query.filter(Complaint.tenant_id == user.tenant_id)
    total = query.count()
    by_status = dict(db.query(Complaint.status, func.count(Complaint.id)).group_by(Complaint.status).all())
    by_category = dict(db.query(Complaint.category, func.count(Complaint.id)).filter(Complaint.category.isnot(None)).group_by(Complaint.category).all())
    by_risk = dict(db.query(Complaint.risk_level, func.count(Complaint.id)).filter(Complaint.risk_level.isnot(None)).group_by(Complaint.risk_level).all())
    return {"total_complaints": total, "by_status": by_status, "by_category": by_category, "by_risk_level": by_risk}


@router.get("/analytics/performance")
async def get_performance_metrics(user: User = Depends(require_officer_or_admin), db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    from app.models.escalation import Escalation

    wo_query = db.query(WorkOrder)
    c_query = db.query(Complaint)
    if user.tenant_id:
        wo_query = wo_query.filter(WorkOrder.tenant_id == user.tenant_id)
        c_query = c_query.filter(Complaint.tenant_id == user.tenant_id)

    # Average resolution time (hours) per category
    completed_orders = wo_query.filter(WorkOrder.completed_at.isnot(None)).all()
    resolution_times: dict[str, list[float]] = {}
    sla_breaches = 0
    sla_total = 0
    for wo in completed_orders:
        complaint = db.query(Complaint).filter(Complaint.id == wo.complaint_id).first()
        if not complaint:
            continue
        created = wo.created_at
        completed = wo.completed_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        hours = (completed - created).total_seconds() / 3600
        cat = complaint.category or "UNKNOWN"
        resolution_times.setdefault(cat, []).append(hours)
        if wo.sla_deadline:
            sla_dl = wo.sla_deadline
            if sla_dl.tzinfo is None:
                sla_dl = sla_dl.replace(tzinfo=timezone.utc)
            sla_total += 1
            if completed > sla_dl:
                sla_breaches += 1

    avg_resolution_by_category = {
        cat: round(sum(times) / len(times), 1)
        for cat, times in resolution_times.items()
    }
    sla_breach_rate = round((sla_breaches / sla_total * 100), 1) if sla_total > 0 else 0.0

    # Contractor performance
    contractor_stats: dict[str, dict] = {}
    for wo in completed_orders:
        if not wo.contractor_id:
            continue
        cid = str(wo.contractor_id)
        if cid not in contractor_stats:
            contractor = db.query(Contractor).filter(Contractor.id == cid).first()
            contractor_stats[cid] = {
                "name": contractor.name if contractor else cid,
                "completed": 0,
                "total_hours": 0.0,
            }
        contractor_stats[cid]["completed"] += 1
        created = wo.created_at
        completed_at = wo.completed_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        contractor_stats[cid]["total_hours"] += (completed_at - created).total_seconds() / 3600

    contractor_performance = [
        {
            "contractor_id": cid,
            "name": stats["name"],
            "completed_orders": stats["completed"],
            "avg_resolution_hours": round(stats["total_hours"] / stats["completed"], 1) if stats["completed"] else 0,
        }
        for cid, stats in contractor_stats.items()
    ]

    # Escalation count
    escalation_count = db.query(Escalation).join(
        Complaint, Escalation.complaint_id == Complaint.id
    ).filter(Complaint.tenant_id == user.tenant_id).count() if user.tenant_id else db.query(Escalation).count()

    return {
        "avg_resolution_hours_by_category": avg_resolution_by_category,
        "sla_breach_rate_percent": sla_breach_rate,
        "sla_breaches": sla_breaches,
        "sla_total_measured": sla_total,
        "contractor_performance": contractor_performance,
        "total_escalations": escalation_count,
    }


@router.get("/contractors")
async def list_contractors(user: User = Depends(require_officer_or_admin), db: Session = Depends(get_db)):
    query = db.query(Contractor)
    if user.tenant_id:
        query = query.filter(Contractor.tenant_id == user.tenant_id)
    contractors = query.all()
    return {
        "contractors": [
            {"id": str(c.id), "name": c.name, "specializations": c.specializations,
             "rating": c.rating, "active_workload": c.active_workload, "zone": c.zone}
            for c in contractors
        ]
    }
