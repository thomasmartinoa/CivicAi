from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    suite: Mapped[str] = mapped_column(String(40), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(80), nullable=False)
    dataset_hash: Mapped[str | None] = mapped_column(String(64))
    git_sha: Mapped[str | None] = mapped_column(String(40))
    # Which configuration produced these numbers: "baseline_keyword",
    # "llm_no_rag" or "v2_full". This is what makes the comparison table possible.
    config_label: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    results: Mapped[list["EvalResult"]] = relationship(back_populates="eval_run")


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    eval_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    detail_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    eval_run: Mapped["EvalRun"] = relationship(back_populates="results")
