import pytest

from app.db.models.core import Tenant
from app.services.seed import seed_database
from app.services.tenancy import NoTenantConfigured, resolve_tenant_id


def test_an_explicit_tenant_is_used_when_it_exists(db_session):
    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    assert resolve_tenant_id(db_session, tenant.id) == tenant.id


def test_an_unknown_tenant_is_rejected(db_session):
    seed_database(db_session)
    with pytest.raises(NoTenantConfigured, match="not-a-tenant"):
        resolve_tenant_id(db_session, "not-a-tenant")


def test_no_request_falls_back_to_the_only_tenant(db_session):
    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    assert resolve_tenant_id(db_session, None) == tenant.id


def test_an_empty_database_fails_loudly(db_session):
    """route_node fails closed on a tenant-less complaint, so creation must not
    produce one. v1 silently used whichever tenant happened to be first."""
    with pytest.raises(NoTenantConfigured):
        resolve_tenant_id(db_session, None)


def test_ambiguity_fails_rather_than_guessing(db_session):
    db_session.add_all([Tenant(name="A"), Tenant(name="B")])
    db_session.commit()
    with pytest.raises(NoTenantConfigured, match="ambiguous"):
        resolve_tenant_id(db_session, None)
