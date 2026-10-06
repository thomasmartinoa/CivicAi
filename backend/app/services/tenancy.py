"""Resolving which tenant a complaint belongs to, and what that tenant's
response windows are.

`route_node` fails closed on a complaint with no `tenant_id`, so creation must
never produce one. v1 silently assigned whichever tenant happened to be first,
which is indistinguishable from a correct assignment until there are two.

The SLA window lives here rather than in the work_order node because it is a
municipal policy, not a program constant: two tenants on one deployment may
answer a critical complaint in 4 hours and 6. The node receives a callable and
never reads the database itself.
"""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.constants import DEFAULT_SLA_HOURS, RiskLevel
from app.db.models.core import Tenant

logger = logging.getLogger(__name__)


class NoTenantConfigured(RuntimeError):
    pass


def sla_hours_for(tenant, risk_level: RiskLevel) -> int:
    """This tenant's response window for a risk band, in hours.

    Falls back to DEFAULT_SLA_HOURS and logs when the tenant has configured
    nothing for the band, or configured something that is not a positive number
    — a typo in a config blob must not become a deadline, and must not raise
    either: every complaint needs a window.
    """
    configured = (tenant.config or {}).get("sla_hours", {}) if tenant is not None else {}
    value = configured.get(risk_level.value) if isinstance(configured, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        if value is not None:
            logger.warning("tenant %s has an invalid sla_hours entry for %s: %r; using the default",
                           getattr(tenant, "id", None), risk_level.value, value)
        else:
            logger.warning("tenant %s configures no sla_hours for %s; using the default",
                           getattr(tenant, "id", None), risk_level.value)
        return DEFAULT_SLA_HOURS[risk_level]
    return int(value)


def tenant_sla_lookup(session_factory: Callable) -> Callable[[str | None, RiskLevel], int]:
    """The callable build_deps hands to the work_order node.

    Takes the complaint's tenant id rather than a Tenant, so the node stays free
    of the database. A tenant that cannot be found gets the defaults: an unknown
    tenant is a bug worth logging, not a reason to leave a complaint with no
    deadline.
    """

    def lookup(tenant_id: str | None, risk_level: RiskLevel) -> int:
        if tenant_id is None:
            return DEFAULT_SLA_HOURS[risk_level]
        session = session_factory()
        try:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                logger.warning("tenant %s not found; using the default SLA window", tenant_id)
                return DEFAULT_SLA_HOURS[risk_level]
            return sla_hours_for(tenant, risk_level)
        finally:
            session.close()

    return lookup


def resolve_tenant_id(session: Session, requested: str | None) -> str:
    """The tenant for a new complaint. Never guesses."""
    if requested:
        exists = session.query(Tenant).filter(Tenant.id == requested).one_or_none()
        if exists is None:
            raise NoTenantConfigured(f"tenant {requested!r} does not exist")
        return exists.id

    tenants = session.query(Tenant).limit(2).all()
    if not tenants:
        raise NoTenantConfigured(
            "no tenant exists; seed the database or supply tenant_id explicitly"
        )
    if len(tenants) > 1:
        raise NoTenantConfigured(
            "tenant is ambiguous: more than one exists and none was supplied"
        )
    return tenants[0].id
