from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent, PipelineContext
from app.services.email import email_service
from app.services.websocket import ws_manager


class TrackingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="TrackingAgent")

    async def process(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        tracking_id = context.data.get("tracking_id", context.complaint_id)
        citizen_email = context.data.get("citizen_email", "")

        if citizen_email:
            await email_service.send_complaint_confirmation(
                citizen_email, tracking_id,
                complaint_id=context.complaint_id, db=db
            )

        await ws_manager.send_update(tracking_id, {
            "type": "status_update",
            "tracking_id": tracking_id,
            "status": "assigned",
            "category": context.data.get("category"),
            "risk_level": context.data.get("risk_level"),
            "department": context.data.get("department_name"),
            "message": "Your complaint has been processed and assigned to the relevant department.",
        })

        context.status = "assigned"
        self.log(f"Notifications sent for complaint {tracking_id}")
        return context


JURISDICTION_ESCALATION = {"ward": "block", "block": "district", "district": "city", "city": "state"}


def _find_next_contractor(db, tenant_id, category, current_contractor_id, district=None):
    """Find the next best contractor, excluding the currently assigned one."""
    from app.models.contractor import Contractor
    contractors = db.query(Contractor).filter(
        Contractor.tenant_id == tenant_id,
        Contractor.id != current_contractor_id,
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
        if district and c.zone and c.zone.lower() == district.lower():
            score += 10
        scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored else None


async def check_sla_deadlines(db: Session):
    from app.models.work_order import WorkOrder
    from app.models.complaint import Complaint
    from app.models.contractor import Contractor
    from app.models.escalation import Escalation

    now = datetime.now(timezone.utc)
    active_orders = db.query(WorkOrder).filter(
        WorkOrder.status.in_(["created", "assigned", "in_progress"])
    ).all()

    for order in active_orders:
        if not order.sla_deadline:
            continue
        complaint = db.query(Complaint).filter(Complaint.id == order.complaint_id).first()
        if not complaint:
            continue

        sla_deadline = order.sla_deadline
        if sla_deadline.tzinfo is None:
            sla_deadline = sla_deadline.replace(tzinfo=timezone.utc)
        created_at = order.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        time_remaining = (sla_deadline - now).total_seconds()
        total_time = (sla_deadline - created_at).total_seconds()
        if total_time <= 0:
            continue
        elapsed_pct = 1 - (time_remaining / total_time)

        if 0.50 <= elapsed_pct < 0.75:
            # 50% elapsed: early warning to citizen
            await email_service.send_status_update(
                complaint.citizen_email, complaint.tracking_id,
                "Your complaint is being actively worked on — SLA deadline approaching",
                complaint_id=complaint.id, db=db,
            )

        elif 0.75 <= elapsed_pct < 1.0:
            # 75% elapsed: urgent SLA warning
            await email_service.send_status_update(
                complaint.citizen_email, complaint.tracking_id,
                "SLA warning — escalating priority",
                complaint_id=complaint.id, db=db,
            )

        elif elapsed_pct >= 1.0:
            current_level = (
                "ward" if complaint.ward else
                "block" if complaint.block else
                "district"
            )
            next_level = JURISDICTION_ESCALATION.get(current_level, "state")

            # Auto-reassign to next best contractor
            new_contractor = _find_next_contractor(
                db,
                complaint.tenant_id,
                complaint.category or "",
                order.contractor_id or "",
                complaint.district,
            )

            if new_contractor:
                # Decrement old contractor workload
                if order.contractor_id:
                    old_contractor = db.query(Contractor).filter(Contractor.id == order.contractor_id).first()
                    if old_contractor:
                        old_contractor.active_workload = max(0, (old_contractor.active_workload or 1) - 1)

                order.contractor_id = str(new_contractor.id)
                order.status = "assigned"
                new_contractor.active_workload = (new_contractor.active_workload or 0) + 1
                reassign_note = f"Auto-reassigned to {new_contractor.name} after SLA breach."
            else:
                reassign_note = "No available contractor for reassignment."

            escalation = Escalation(
                complaint_id=complaint.id,
                from_level=current_level,
                to_level=next_level,
                reason=f"SLA breached at {order.sla_deadline.isoformat()}. {reassign_note}",
            )
            db.add(escalation)
            complaint.status = "escalated"
            db.commit()

            await email_service.send_status_update(
                complaint.citizen_email, complaint.tracking_id,
                f"Escalated to {next_level} level — SLA breached. New contractor assigned automatically.",
                complaint_id=complaint.id, db=db,
            )
