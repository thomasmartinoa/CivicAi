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


def test_sla_hours_come_from_the_tenant_config(db_session):
    """The window is the tenant's policy, not a dict in a node."""
    from app.constants import RiskLevel
    from app.services.tenancy import sla_hours_for

    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    assert sla_hours_for(tenant, RiskLevel.CRITICAL) == 4
    assert sla_hours_for(tenant, RiskLevel.LOW) == 168


def test_a_missing_band_falls_back_and_says_so(db_session, caplog):
    from app.constants import DEFAULT_SLA_HOURS, RiskLevel
    from app.services.tenancy import sla_hours_for

    tenant = Tenant(name="Sparse Council", config={"sla_hours": {"critical": 2}})
    db_session.add(tenant)
    db_session.flush()
    assert sla_hours_for(tenant, RiskLevel.CRITICAL) == 2
    with caplog.at_level("WARNING"):
        assert sla_hours_for(tenant, RiskLevel.HIGH) == DEFAULT_SLA_HOURS[RiskLevel.HIGH]
    assert "high" in caplog.text


def test_a_tenant_with_no_sla_config_uses_the_defaults(db_session):
    from app.constants import DEFAULT_SLA_HOURS, RiskLevel
    from app.services.tenancy import sla_hours_for

    tenant = Tenant(name="Brand New Council", config={})
    db_session.add(tenant)
    db_session.flush()
    assert sla_hours_for(tenant, RiskLevel.MEDIUM) == DEFAULT_SLA_HOURS[RiskLevel.MEDIUM]


def test_a_nonsense_configured_window_is_refused(db_session, caplog):
    """A string or a negative number in the config must not become a deadline."""
    from app.constants import DEFAULT_SLA_HOURS, RiskLevel
    from app.services.tenancy import sla_hours_for

    tenant = Tenant(name="Typo Council", config={"sla_hours": {"high": "soon", "low": -5}})
    db_session.add(tenant)
    db_session.flush()
    with caplog.at_level("WARNING"):
        assert sla_hours_for(tenant, RiskLevel.HIGH) == DEFAULT_SLA_HOURS[RiskLevel.HIGH]
        assert sla_hours_for(tenant, RiskLevel.LOW) == DEFAULT_SLA_HOURS[RiskLevel.LOW]


def test_the_sla_lookup_closure_reads_the_tenant(db_session):
    """What build_deps hands the work_order node: a callable taking the state's
    tenant id, so the node itself still touches no database."""
    from app.constants import DEFAULT_SLA_HOURS, RiskLevel
    from app.services.tenancy import tenant_sla_lookup

    seeded = seed_database(db_session)
    lookup = tenant_sla_lookup(lambda: db_session)
    assert lookup(seeded["tenant_id"], RiskLevel.CRITICAL) == 4
    assert lookup(None, RiskLevel.CRITICAL) == DEFAULT_SLA_HOURS[RiskLevel.CRITICAL]
    assert lookup("does-not-exist", RiskLevel.HIGH) == DEFAULT_SLA_HOURS[RiskLevel.HIGH]
