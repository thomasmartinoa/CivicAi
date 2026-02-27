import uuid
from sqlalchemy.orm import Session
from app.models.tenant import Tenant
from app.models.user import User
from app.models.department import Department
from app.models.contractor import Contractor
from app.utils.auth import hash_password


def seed_database(db: Session):
    if db.query(Tenant).first():
        return {"message": "Database already seeded"}

    tenant = Tenant(id=str(uuid.uuid4()), name="Bangalore Municipal Corporation",
        config={"sla_hours": {"critical": 4, "high": 24, "medium": 72, "low": 168}})
    db.add(tenant)

    admin = User(tenant_id=tenant.id, email="admin@civicai.gov", name="System Admin",
        role="admin", password_hash=hash_password("admin123"))
    db.add(admin)

    departments_data = [
        ("Public Works Department", ["ROADS", "CONSTRUCTION"], "Officer Ramesh"),
        ("Electricity Board", ["ELECTRICITY"], "Officer Priya"),
        ("Water Supply Department", ["WATER"], "Officer Kumar"),
        ("Sanitation Department", ["SANITATION", "SEWAGE"], "Officer Lakshmi"),
        ("Parks & Recreation", ["PUBLIC_SPACES"], "Officer Suresh"),
        ("Health Department", ["HEALTH"], "Officer Meera"),
        ("Fire Department", ["FIRE_HAZARD"], "Officer Vijay"),
        ("Flood Control Authority", ["FLOODING"], "Officer Anita"),
        ("Animal Control", ["STRAY_ANIMALS"], "Officer Raj"),
        ("Education Department", ["EDUCATION"], "Officer Deepa"),
    ]

    for dept_name, categories, officer_name in departments_data:
        officer = User(tenant_id=tenant.id, email=f"{officer_name.lower().replace(' ', '.')}@civicai.gov",
            name=officer_name, role="officer", password_hash=hash_password("officer123"))
        db.add(officer)
        db.flush()
        dept = Department(tenant_id=tenant.id, name=dept_name, category_mapping=categories, head_officer_id=officer.id)
        db.add(dept)

    contractors_data = [
        ("RoadFix India Pvt Ltd", ["ROADS", "CONSTRUCTION"], 4.5, "South Bangalore", 2),
        ("PowerGrid Solutions", ["ELECTRICITY"], 4.2, "North Bangalore", 1),
        ("AquaFlow Services", ["WATER", "SEWAGE", "FLOODING"], 4.0, "East Bangalore", 3),
        ("CleanCity Corp", ["SANITATION", "SEWAGE"], 3.8, "West Bangalore", 2),
        ("GreenScape Pvt Ltd", ["PUBLIC_SPACES"], 4.3, "Central Bangalore", 1),
        ("SafeGuard Services", ["FIRE_HAZARD", "ELECTRICITY"], 4.6, "South Bangalore", 0),
        ("BuildRight Construction", ["ROADS", "CONSTRUCTION", "FLOODING"], 4.1, "North Bangalore", 4),
        ("MediCare Infrastructure", ["HEALTH", "EDUCATION"], 3.9, "East Bangalore", 1),
    ]

    for name, specs, rating, zone, workload in contractors_data:
        contractor = Contractor(tenant_id=tenant.id, name=name, specializations=specs,
            rating=rating, active_workload=workload, zone=zone)
        db.add(contractor)

    db.commit()
    return {"message": "Database seeded successfully", "tenant_id": str(tenant.id)}
