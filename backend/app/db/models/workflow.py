from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    contractor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("contractors.id"))
    officer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created", index=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    # Where the cost estimate came from, so the UI can cite it. v1 used a
    # hardcoded per-category dict and recorded nothing.
    cost_basis: Mapped[str | None] = mapped_column(Text)
    materials: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # v1 identified cluster orders with `notes LIKE '%[CLUSTER]%'`.
    is_cluster: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cluster_size: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_photo: Mapped[str | None] = mapped_column(String(500))

    complaint: Mapped["Complaint"] = relationship(back_populates="work_order")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    from_level: Mapped[str] = mapped_column(String(50), nullable=False)
    to_level: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    escalated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    complaint: Mapped["Complaint"] = relationship(back_populates="escalations")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("complaints.id"))
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Idempotency guard. v1 re-sent SLA warnings every 5 minutes because nothing
    # recorded that a given warning had already gone out.
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    brief_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    new_complaints: Mapped[int] = mapped_column(Integer, default=0)
    resolved_today: Mapped[int] = mapped_column(Integer, default=0)
    sla_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    escalations_today: Mapped[int] = mapped_column(Integer, default=0)
    clusters_detected: Mapped[int] = mapped_column(Integer, default=0)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    # False when the LLM path failed and template text was used instead. v1 served
    # fallback text for its entire life without recording that it had.
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
