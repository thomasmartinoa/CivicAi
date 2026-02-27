import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Contractor(Base):
    __tablename__ = "contractors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specializations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    active_workload: Mapped[int] = mapped_column(Integer, default=0)
    zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="contractors")
