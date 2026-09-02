"""Importing this package registers every model on Base.metadata.

Alembic autogenerate and Base.metadata.create_all both depend on it, so any new
model module must be added here.
"""

from app.db.models.core import Contractor, Department, Tenant, User

__all__ = ["Contractor", "Department", "Tenant", "User"]
