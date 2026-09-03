"""Idempotent development seed data.

Departments are derived from app.constants.CATEGORY_DEPARTMENT rather than a
separate hand-written list. v1 kept the two in parallel and they drifted, which
left CONSTRUCTION and SEWAGE pointing at departments that were never created.
"""

import bcrypt
from sqlalchemy.orm import Session

from app.constants import CATEGORY_DEPARTMENT, Category
from app.db.models.core import Contractor, Department, Tenant, User

_OFFICER_NAMES = {
    "Public Works Department": "Officer Ramesh",
    "Electricity Board": "Officer Priya",
    "Water Supply Department": "Officer Kumar",
    "Sanitation Department": "Officer Lakshmi",
    "Parks & Recreation": "Officer Suresh",
    "Health Department": "Officer Meera",
    "Fire Department": "Officer Vijay",
    "Flood Control Authority": "Officer Anita",
    "Animal Control": "Officer Raj",
    "Education Department": "Officer Deepa",
}

_CONTRACTORS: list[tuple[str, list[Category], float, str, int]] = [
    ("RoadFix India Pvt Ltd", [Category.ROADS, Category.CONSTRUCTION], 4.5, "South Bangalore", 2),
    ("PowerGrid Solutions", [Category.ELECTRICITY], 4.2, "North Bangalore", 1),
    ("AquaFlow Services", [Category.WATER, Category.SEWAGE, Category.FLOODING], 4.0, "East Bangalore", 3),
    ("CleanCity Corp", [Category.SANITATION, Category.SEWAGE], 3.8, "West Bangalore", 2),
    ("GreenScape Pvt Ltd", [Category.PUBLIC_SPACES], 4.3, "Central Bangalore", 1),
    ("SafeGuard Services", [Category.FIRE_HAZARD, Category.ELECTRICITY], 4.6, "South Bangalore", 0),
    ("BuildRight Construction", [Category.ROADS, Category.CONSTRUCTION, Category.FLOODING], 4.1, "North Bangalore", 4),
    ("MediCare Infrastructure", [Category.HEALTH, Category.EDUCATION], 3.9, "East Bangalore", 1),
    ("PawCare Animal Services", [Category.STRAY_ANIMALS], 4.0, "Central Bangalore", 0),
]


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _departments_from_constants() -> dict[str, list[str]]:
    """Invert CATEGORY_DEPARTMENT into {department_name: [categories]}."""
    grouped: dict[str, list[str]] = {}
    for category, dept_name in CATEGORY_DEPARTMENT.items():
        grouped.setdefault(dept_name, []).append(category.value)
    return grouped


def seed_database(db: Session) -> dict:
    existing = db.query(Tenant).first()
    if existing:
        return {"message": "Database already seeded", "tenant_id": existing.id}

    tenant = Tenant(
        name="Bangalore Municipal Corporation",
        config={"sla_hours": {"critical": 4, "high": 24, "medium": 72, "low": 168}},
    )
    db.add(tenant)
    db.flush()

    db.add(User(
        tenant_id=tenant.id, email="admin@civicai.gov", name="System Admin",
        role="admin", password_hash=_hash("admin123"),
    ))

    for dept_name, categories in _departments_from_constants().items():
        officer_name = _OFFICER_NAMES.get(dept_name, f"Officer {dept_name.split()[0]}")
        officer = User(
            tenant_id=tenant.id,
            email=f"{officer_name.lower().replace(' ', '.')}@civicai.gov",
            name=officer_name, role="officer", password_hash=_hash("officer123"),
        )
        db.add(officer)
        db.flush()
        db.add(Department(
            tenant_id=tenant.id, name=dept_name,
            categories=sorted(categories), head_officer_id=officer.id,
        ))

    for name, specs, rating, zone, workload in _CONTRACTORS:
        db.add(Contractor(
            tenant_id=tenant.id, name=name,
            specializations=[c.value for c in specs],
            rating=rating, active_workload=workload, zone=zone,
        ))

    db.commit()
    return {"message": "Database seeded successfully", "tenant_id": tenant.id}
