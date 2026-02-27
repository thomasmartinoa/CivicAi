import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    citizen_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    citizen_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    citizen_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")

    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ward: Mapped[str | None] = mapped_column(String(100), nullable=True)
    block: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)

    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    tenant = relationship("Tenant", back_populates="complaints")
    media = relationship("ComplaintMedia", back_populates="complaint")
    work_order = relationship("WorkOrder", back_populates="complaint", uselist=False)
    escalations = relationship("Escalation", back_populates="complaint")


class ComplaintMedia(Base):
    __tablename__ = "complaint_media"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    complaint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("complaints.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    complaint = relationship("Complaint", back_populates="media")
