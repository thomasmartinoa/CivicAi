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
            await email_service.send_complaint_confirmation(citizen_email, tracking_id)

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


async def check_sla_deadlines(db: Session):
    from app.models.work_order import WorkOrder
    from app.models.complaint import Complaint
    from app.models.escalation import Escalation

    now = datetime.now(timezone.utc)
    active_orders = db.query(WorkOrder).filter(
        WorkOrder.status.in_(["created", "accepted", "in_progress"])
    ).all()

    for order in active_orders:
        if not order.sla_deadline: continue
        complaint = db.query(Complaint).filter(Complaint.id == order.complaint_id).first()
        if not complaint: continue

        time_remaining = (order.sla_deadline - now).total_seconds()
        total_time = (order.sla_deadline - order.created_at).total_seconds()
        if total_time <= 0: continue
        elapsed_pct = 1 - (time_remaining / total_time)

        if 0.75 <= elapsed_pct < 1.0:
            await email_service.send_status_update(complaint.citizen_email, complaint.tracking_id, "SLA warning - escalating priority")
        elif elapsed_pct >= 1.0:
            current_level = complaint.ward and "ward" or complaint.block and "block" or "district"
            next_level = JURISDICTION_ESCALATION.get(current_level, "state")
            escalation = Escalation(
                complaint_id=complaint.id, from_level=current_level,
                to_level=next_level, reason=f"SLA breached. Deadline was {order.sla_deadline.isoformat()}",
            )
            db.add(escalation)
            db.commit()
            await email_service.send_status_update(complaint.citizen_email, complaint.tracking_id, f"Escalated to {next_level} level due to SLA breach")
