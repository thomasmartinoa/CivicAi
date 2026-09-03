from app.constants import CATEGORY_DEPARTMENT, Category
from app.db.models.core import Contractor, Department, Tenant, User
from app.services.seed import seed_database


def test_seed_creates_a_tenant_admin_departments_and_contractors(db_session):
    result = seed_database(db_session)

    assert result["tenant_id"]
    assert db_session.query(Tenant).count() == 1
    assert db_session.query(User).filter(User.role == "admin").count() == 1
    assert db_session.query(Department).count() > 0
    assert db_session.query(Contractor).count() > 0


def test_seed_is_idempotent(db_session):
    seed_database(db_session)
    before = db_session.query(Department).count()
    seed_database(db_session)
    assert db_session.query(Department).count() == before


def test_every_mapped_department_actually_exists(db_session):
    """v1 Bug 3: CONSTRUCTION and SEWAGE mapped to departments never seeded."""
    seed_database(db_session)
    seeded_names = {d.name for d in db_session.query(Department).all()}

    for category, dept_name in CATEGORY_DEPARTMENT.items():
        assert dept_name in seeded_names, f"{category} maps to unseeded '{dept_name}'"


def test_every_category_is_claimed_by_exactly_one_department(db_session):
    seed_database(db_session)
    claimed: list[str] = []
    for dept in db_session.query(Department).all():
        claimed.extend(dept.categories or [])

    assert sorted(claimed) == sorted(c.value for c in Category)


def test_admin_password_is_hashed_not_stored_plain(db_session):
    seed_database(db_session)
    admin = db_session.query(User).filter(User.role == "admin").one()
    assert admin.password_hash
    assert "admin123" not in admin.password_hash
