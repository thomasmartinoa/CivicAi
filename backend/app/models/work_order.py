import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=True)
    contractor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("contractors.id"), nullable=True)
    officer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    materials: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_photo: Mapped[str | None] = mapped_column(String(500), nullable=True)  # path to proof photo

    complaint = relationship("Complaint", back_populates="work_order")
    contractor = relationship("Contractor")
