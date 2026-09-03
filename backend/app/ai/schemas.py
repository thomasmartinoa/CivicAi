"""Typed outputs for every AI step.

These are what `.with_structured_output(...)` binds to, so the model is
constrained at generation time rather than parsed afterwards. v1 asked for JSON
in a prompt, scraped it out of the response with a substring search, and wrote
whatever came back to the database unvalidated.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.constants import Category, RiskLevel


def band_for_score(score: int) -> RiskLevel:
    """Map a 0-100 priority score onto its risk band."""
    if score >= 76:
        return RiskLevel.CRITICAL
    if score >= 51:
        return RiskLevel.HIGH
    if score >= 26:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ── plain inputs (not model-generated) ───────────────────────────────────


class Coords(BaseModel):
    latitude: float
    longitude: float


class MediaRef(BaseModel):
    file_path: str
    media_type: str
    original_filename: str | None = None


class LocationInfo(BaseModel):
    address: str = ""
    ward: str = ""
    block: str = ""
    district: str = ""
    state: str = ""


# ── model-generated ──────────────────────────────────────────────────────


class MediaInsight(BaseModel):
    """What one image or audio file contributed to the complaint."""

    file_path: str
    media_type: str
    text: str


class ValidationResult(BaseModel):
    is_valid: bool
    what_happened: str = ""
    rejection_reason: str | None = None
    severity_keywords: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    category: Category
    subcategory: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class RiskAssessment(BaseModel):
    priority_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    category_severity: int = Field(default=0, ge=0, le=25)
    population_impact: int = Field(default=0, ge=0, le=25)
    safety_risk: int = Field(default=0, ge=0, le=25)
    urgency: int = Field(default=0, ge=0, le=25)
    reasoning: str = ""

    @model_validator(mode="after")
    def _band_must_match_score(self):
        expected = band_for_score(self.priority_score)
        if self.risk_level != expected:
            raise ValueError(
                f"risk_level {self.risk_level!r} contradicts priority_score "
                f"{self.priority_score} (expected {expected.value!r})"
            )
        return self


class RoutingDecision(BaseModel):
    department_name: str
    department_id: str | None = None
    contractor_id: str | None = None
    contractor_name: str | None = None
    jurisdiction_level: Literal["ward", "block", "district", "city"]
    justification: str = ""


class WorkOrderDraft(BaseModel):
    sla_hours: int
    sla_deadline: datetime
    estimated_cost: float
    cost_basis: str = ""
    materials: str = ""
    summary: str = ""


# ── bookkeeping carried through the graph ────────────────────────────────


class NodeDecision(BaseModel):
    """One line of the audit trail, one per node."""

    node: str
    summary: str
    duration_ms: int | None = None


class RetrievedChunk(BaseModel):
    """A retrieval hit, so any decision can cite its sources. Used from Phase 2."""

    source: str
    chunk_id: str | None = None
    score: float | None = None
    snippet: str = ""
