from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    departments: Mapped[list["Department"]] = relationship(back_populates="tenant")
    contractors: Mapped[list["Contractor"]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="citizen")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # No department_id: it would close a User <-> Department foreign-key cycle that
    # create_all cannot order and SQLite cannot fix with ALTER TABLE. v1 had the
    # column and never read it. Department.head_officer_id carries this link.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="users")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Categories this department owns. Read by the routing node in Phase 1 —
    # v1 declared this column and then hardcoded the mapping in Python instead.
    categories: Mapped[list | None] = mapped_column(JSON, default=list)
    head_officer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="departments")


class Contractor(Base):
    __tablename__ = "contractors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specializations: Mapped[list | None] = mapped_column(JSON, default=list)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    active_workload: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    zone: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="contractors")


class CitizenOtp(Base):
    """A one-time code for a citizen checking their own past complaints.

    Its own table rather than columns on `User`, because **a citizen has no User
    row**. v1 conflated the two and ended up with half-populated user records for
    people who had only ever filed a complaint. The only identity here is the email
    address a complaint was filed under.

    The code is stored hashed. That does not resist an offline attack — six digits is
    a million guesses — but it does mean a glance at this table, or a copy of it in a
    backup or a screenshot, does not hand someone a working code. Online guessing is
    what `attempts` is for.
    """

    __tablename__ = "citizen_otps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Wrong guesses against this code. A six-digit code is trivially brute-forced
    online without a ceiling."""
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    """Set the moment a code is accepted, so it cannot be replayed."""
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
