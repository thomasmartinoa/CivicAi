"""Resolving which tenant a complaint belongs to.

`route_node` fails closed on a complaint with no `tenant_id`, so creation must
never produce one. v1 silently assigned whichever tenant happened to be first,
which is indistinguishable from a correct assignment until there are two.
"""

from sqlalchemy.orm import Session

from app.db.models.core import Tenant


class NoTenantConfigured(RuntimeError):
    pass


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
