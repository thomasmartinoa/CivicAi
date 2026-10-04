from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    # ── citizen ───────────────────────────────────────────────
    citizen_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    citizen_phone: Mapped[str | None] = mapped_column(String(50))
    citizen_name: Mapped[str | None] = mapped_column(String(255))

    # ── content ───────────────────────────────────────────────
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted", index=True)
    # Why a complaint stopped. v1 folded rejections into an errors list, which is
    # how AI-rejected complaints ended up indistinguishable from unprocessed ones.
    terminal_reason: Mapped[str | None] = mapped_column(String(255))

    # ── AI results ────────────────────────────────────────────
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100))
    priority_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[list | None] = mapped_column(JSON, default=list)

    # ── graph metadata ────────────────────────────────────────
    graph_thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(20))

    # ── location ──────────────────────────────────────────────
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(500))
    ward: Mapped[str | None] = mapped_column(String(100))
    block: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    state: Mapped[str | None] = mapped_column(String(100))

    # ── clustering ────────────────────────────────────────────
    # The lead complaint's id, written on every member of a cluster including
    # the lead itself; NULL means unclustered, which is what the hourly job
    # selects on. Membership lives here rather than on the work order because
    # work_orders.complaint_id is unique -- one grouped order cannot reference
    # ten complaints -- and v1's alternative was `notes LIKE '%[CLUSTER]%'`.
    cluster_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # The prose route_node writes to justify the department and contractor it
    # chose, with [n] citations into `evidence`. Stored because it is what an
    # officer or citizen reads to check the decision, and what the Phase 3 rubric
    # judge scores -- before this it reached state and was discarded, leaving only
    # the one-line AgentStep summary.
    routing_justification: Mapped[str | None] = mapped_column(Text)

    # ── citizen feedback ──────────────────────────────────────
    satisfaction_rating: Mapped[int | None] = mapped_column(Integer)
    satisfaction_comment: Mapped[str | None] = mapped_column(Text)
    verified_fixed: Mapped[bool | None] = mapped_column(Boolean)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── officer email flow ────────────────────────────────────
    email_draft: Mapped[str | None] = mapped_column(Text)
    email_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    media: Mapped[list["ComplaintMedia"]] = relationship(
        back_populates="complaint", cascade="all, delete-orphan"
    )
    work_order: Mapped["WorkOrder | None"] = relationship(
        back_populates="complaint", uselist=False, cascade="all, delete-orphan"
    )
    escalations: Mapped[list["Escalation"]] = relationship(
        back_populates="complaint", cascade="all, delete-orphan"
    )


class ComplaintMedia(Base):
    __tablename__ = "complaint_media"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    complaint: Mapped["Complaint"] = relationship(back_populates="media")
