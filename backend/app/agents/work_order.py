from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent, PipelineContext

SLA_HOURS = {"critical": 4, "high": 24, "medium": 72, "low": 168}


class WorkOrderAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="WorkOrderAgent")

    async def process(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        risk_level = context.data.get("risk_level", "medium")
        sla_hours = SLA_HOURS.get(risk_level, 72)
        now = datetime.now(timezone.utc)

        work_order_data = {
            "complaint_id": context.complaint_id,
            "tenant_id": context.tenant_id,
            "contractor_id": context.data.get("recommended_contractor_id"),
            "department_name": context.data.get("department_name"),
            "status": "created",
            "sla_deadline": (now + timedelta(hours=sla_hours)).isoformat(),
            "sla_hours": sla_hours,
            "estimated_cost": self._estimate_cost(context.data.get("category", ""), risk_level),
            "materials": self._estimate_materials(context.data.get("category", "")),
            "summary": self._generate_summary(context.data),
        }
        context.work_order = work_order_data
        context.status = "work_order_created"
        self.log(f"Work order created. SLA: {sla_hours}h")
        return context

    def _estimate_cost(self, category, risk_level):
        base_costs = {
            "ROADS": 5000, "ELECTRICITY": 3000, "WATER": 4000, "SANITATION": 2000,
            "PUBLIC_SPACES": 3000, "EDUCATION": 8000, "HEALTH": 6000, "FLOODING": 10000,
            "FIRE_HAZARD": 7000, "CONSTRUCTION": 15000, "STRAY_ANIMALS": 1000, "SEWAGE": 5000,
        }
        multiplier = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.8}
        return base_costs.get(category, 5000) * multiplier.get(risk_level, 1.0)

    def _estimate_materials(self, category):
        materials = {
            "ROADS": "Asphalt, gravel, road markers, barriers",
            "ELECTRICITY": "Wiring, transformers, LED bulbs, poles",
            "WATER": "PVC pipes, valves, pumps, testing kits",
            "SANITATION": "Cleaning equipment, bins, drain covers",
            "PUBLIC_SPACES": "Lumber, paint, plants, fencing",
            "SEWAGE": "Manhole covers, drainage pipes, pumps",
            "FLOODING": "Sandbags, pumps, drainage equipment",
            "FIRE_HAZARD": "Extinguishers, barriers, signage",
        }
        return materials.get(category, "To be determined on site inspection")

    def _generate_summary(self, data):
        return (
            f"Category: {data.get('category', 'N/A')} | "
            f"Priority: {data.get('risk_level', 'N/A')} (Score: {data.get('priority_score', 'N/A')}) | "
            f"Location: {data.get('address', 'N/A')} | "
            f"Department: {data.get('department_name', 'N/A')}"
        )
