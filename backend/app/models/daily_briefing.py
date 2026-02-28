import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=True)
    brief_date: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    new_complaints: Mapped[int] = mapped_column(Integer, default=0)
    resolved_today: Mapped[int] = mapped_column(Integer, default=0)
    sla_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    escalations_today: Mapped[int] = mapped_column(Integer, default=0)
    clusters_detected: Mapped[int] = mapped_column(Integer, default=0)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
