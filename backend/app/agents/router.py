from typing import Optional
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, PipelineContext
from app.models.department import Department
from app.models.contractor import Contractor

CATEGORY_DEPARTMENT_MAP = {
    "ROADS": "Public Works Department",
    "ELECTRICITY": "Electricity Board",
    "WATER": "Water Supply Department",
    "SANITATION": "Sanitation Department",
    "PUBLIC_SPACES": "Parks & Recreation",
    "EDUCATION": "Education Department",
    "HEALTH": "Health Department",
    "FLOODING": "Flood Control Authority",
    "FIRE_HAZARD": "Fire Department",
    "CONSTRUCTION": "Building & Construction Authority",
    "STRAY_ANIMALS": "Animal Control",
    "SEWAGE": "Sewage & Drainage Board",
}


class RoutingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="RoutingAgent")

    async def process(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        category = context.data.get("category", "UNKNOWN")
        tenant_id = context.tenant_id
        dept_name = CATEGORY_DEPARTMENT_MAP.get(category, "General Administration")
        department = None
        contractor = None

        if db and tenant_id:
            department = db.query(Department).filter(
                Department.tenant_id == tenant_id, Department.name == dept_name
            ).first()
            contractor = self._find_best_contractor(db, tenant_id, category, context.data.get("district"))

        context.routing = {
            "department_name": dept_name,
            "department_id": str(department.id) if department else None,
            "contractor_id": str(contractor.id) if contractor else None,
            "contractor_name": contractor.name if contractor else None,
            "jurisdiction_level": self._determine_jurisdiction(context.data),
        }
        context.data["department_name"] = dept_name
        context.data["department_id"] = str(department.id) if department else None
        context.data["recommended_contractor_id"] = str(contractor.id) if contractor else None
        context.data["recommended_contractor_name"] = contractor.name if contractor else None
        context.status = "routed"
        self.log(f"Routed to {dept_name}, contractor: {contractor.name if contractor else 'None'}")
        return context

    def _find_best_contractor(self, db, tenant_id, category, district):
        contractors = db.query(Contractor).filter(Contractor.tenant_id == tenant_id).all()
        if not contractors: return None
        scored = []
        for c in contractors:
            score = 0.0
            if c.specializations and category in c.specializations: score += 40
            score += (c.rating or 0) * 6
            score += max(0, 20 - (c.active_workload or 0) * 2)
            if district and c.zone and c.zone.lower() == district.lower(): score += 10
            scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else None

    def _determine_jurisdiction(self, data):
        if data.get("ward"): return "ward"
        if data.get("block"): return "block"
        if data.get("district"): return "district"
        return "city"
