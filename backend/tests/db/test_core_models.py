from app.constants import Category
from app.db.models.core import Contractor, Department, Tenant, User


def test_tenant_gets_a_uuid_string_primary_key(db_session):
    tenant = Tenant(name="Bangalore Municipal Corporation")
    db_session.add(tenant)
    db_session.commit()

    assert isinstance(tenant.id, str)
    assert len(tenant.id) == 36


def test_department_stores_categories_as_json(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.flush()

    dept = Department(
        tenant_id=tenant.id,
        name="Public Works Department",
        categories=[Category.ROADS.value, Category.CONSTRUCTION.value],
    )
    db_session.add(dept)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.query(Department).one()
    assert reloaded.categories == ["ROADS", "CONSTRUCTION"]


def test_contractor_defaults_are_sane(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.flush()

    contractor = Contractor(tenant_id=tenant.id, name="RoadFix India")
    db_session.add(contractor)
    db_session.commit()

    assert contractor.rating == 0.0
    assert contractor.active_workload == 0


def test_user_role_defaults_to_citizen(db_session):
    user = User(email="a@b.com", name="A")
    db_session.add(user)
    db_session.commit()
    assert user.role == "citizen"


def test_user_and_department_have_no_circular_foreign_key():
    """create_all cannot order a cycle, and SQLite cannot repair one afterwards."""
    assert not hasattr(User, "department_id")


def test_created_at_is_populated_automatically(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.commit()
    assert tenant.created_at is not None
