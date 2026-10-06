import pytest
from sqlalchemy.exc import IntegrityError

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


def test_nullable_is_inferred_from_optional_annotations(db_session):
    """SQLAlchemy < 2.0.52 cannot parse `Mapped[X | None]` on Python 3.14.

    Pinning this makes a downgrade fail here rather than at import time.
    """
    assert Tenant.__table__.c.config.nullable is True
    assert Tenant.__table__.c.name.nullable is False
    assert Contractor.__table__.c.zone.nullable is True


def test_duplicate_email_within_a_tenant_is_rejected(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.flush()

    db_session.add(User(tenant_id=tenant.id, email="dup@b.com", name="A"))
    db_session.add(User(tenant_id=tenant.id, email="dup@b.com", name="B"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_same_email_is_allowed_across_different_tenants(db_session):
    tenant_a = Tenant(name="BMC")
    tenant_b = Tenant(name="Pune Municipal Corporation")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    db_session.add(User(tenant_id=tenant_a.id, email="shared@b.com", name="A"))
    db_session.add(User(tenant_id=tenant_b.id, email="shared@b.com", name="B"))
    db_session.commit()

    assert db_session.query(User).count() == 2


def test_foreign_keys_are_enforced(db_session):
    """SQLite defaults PRAGMA foreign_keys to OFF; we turn it on at connect."""
    from app.db.models.workflow import WorkOrder
    db_session.add(WorkOrder(complaint_id="does-not-exist"))
    with pytest.raises(IntegrityError):
        db_session.commit()
