"""Typed outputs for every AI step.

These are what `.with_structured_output(...)` binds to, so the model is
constrained at generation time rather than parsed afterwards. v1 asked for JSON
in a prompt, scraped it out of the response with a substring search, and wrote
whatever came back to the database unvalidated.
"""

from pydantic import BaseModel, Field, model_validator

from app.constants import Category, JurisdictionLevel, RiskLevel


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

    file_path: str = Field(description="Path of the media file this insight was extracted from")
    media_type: str = Field(description="Kind of media, e.g. 'image' or 'audio'")
    text: str = Field(description="What the media shows or says, in plain text")


class VisionObservation(BaseModel):
    """What a vision model reports about one photograph.

    Deliberately smaller than MediaInsight: the model is not told the file path
    or media type, so it cannot hallucinate them. The node maps this into a
    MediaInsight, supplying those itself.
    """

    text: str = Field(description="What infrastructure problem is visible, in one or two sentences")
    shows_infrastructure_problem: bool = Field(
        description="False if the image shows nothing a municipality would act on"
    )
    apparent_severity: str = Field(
        default="unknown",
        description="How severe the visible problem looks: minor, moderate, severe, or unknown",
    )


class ValidationResult(BaseModel):
    is_valid: bool = Field(description="Whether this report describes an infrastructure problem to act on")
    what_happened: str = Field(default="", description="One-sentence restatement of the reported problem")
    rejection_reason: str | None = Field(default=None, description="Why the report was rejected, if it was")
    severity_keywords: list[str] = Field(default_factory=list, description="Words in the report signalling severity or danger")


class ClassificationResult(BaseModel):
    category: Category = Field(description="The single infrastructure category this complaint belongs to")
    subcategory: str = Field(default="", description="Optional finer-grained label within the category")
    confidence: float = Field(ge=0.0, le=1.0, description="How confident this classification is, from 0 to 1")
    reasoning: str = Field(default="", description="Brief explanation for why this category was chosen")


class RiskAssessment(BaseModel):
    priority_score: int = Field(ge=0, le=100, description="Overall urgency score, 0-100, the sum of the four factors below")
    risk_level: RiskLevel = Field(description="Risk band matching priority_score: low, medium, high, or critical")
    category_severity: int = Field(default=0, ge=0, le=25, description="How dangerous this class of problem is at its worst, 0-25")
    population_impact: int = Field(default=0, ge=0, le=25, description="How many people the problem plausibly affects, 0-25")
    safety_risk: int = Field(default=0, ge=0, le=25, description="How likely someone is hurt before it is fixed, 0-25")
    urgency: int = Field(default=0, ge=0, le=25, description="How much worse the problem gets if left for a week, 0-25")
    reasoning: str = Field(default="", description="Brief explanation for the scores given")

    @model_validator(mode="after")
    def _band_must_match_score(self):
        expected = band_for_score(self.priority_score)
        if self.risk_level != expected:
            raise ValueError(
                f"risk_level {self.risk_level!r} contradicts priority_score "
                f"{self.priority_score} (expected {expected.value!r})"
            )
        # The four factors default to 0, so a RiskAssessment constructed with
        # only priority_score and risk_level (as several existing tests do)
        # must not be forced to also supply factors that sum correctly. Only
        # check the sum when the caller actually supplied factors.
        # model_fields_set contains only explicitly-passed fields, so this
        # skips the check for callers that omit them entirely (the model
        # always sends all four) while still catching a model that returns
        # explicit zeros against a non-zero score — which `any(factors)`
        # would let through.
        _FACTOR_FIELDS = {"category_severity", "population_impact", "safety_risk", "urgency"}
        if self.model_fields_set & _FACTOR_FIELDS:
            factors = (self.category_severity, self.population_impact, self.safety_risk, self.urgency)
            total = sum(factors)
            if total != self.priority_score:
                raise ValueError(
                    f"risk factors sum to {total}, which contradicts priority_score "
                    f"{self.priority_score} (category_severity={self.category_severity}, "
                    f"population_impact={self.population_impact}, safety_risk={self.safety_risk}, "
                    f"urgency={self.urgency})"
                )
        return self


class RoutingDecision(BaseModel):
    department_name: str = Field(description="Name of the department this complaint should be routed to")
    department_id: str | None = Field(default=None, description="Database ID of the department, if resolved")
    contractor_id: str | None = Field(default=None, description="Database ID of the assigned contractor, if any")
    contractor_name: str | None = Field(default=None, description="Name of the assigned contractor, if any")
    jurisdiction_level: JurisdictionLevel = Field(description="Administrative level this complaint should be handled at")
    justification: str = Field(default="", description="Brief explanation for the routing decision")


class WorkOrderDraft(BaseModel):
    """Note: deliberately has no `sla_deadline` field. An LLM has no reliable
    notion of "now", so Phase 1b's node computes the deadline itself as
    `utcnow() + timedelta(hours=sla_hours)` rather than trusting a
    model-generated timestamp. Do not add it back here."""

    sla_hours: int = Field(ge=1, description="Hours allowed to resolve this work order, counted from creation")
    estimated_cost: float = Field(ge=0.0, description="Estimated cost to resolve the issue, in local currency")
    cost_basis: str = Field(default="", description="Brief explanation of how the cost estimate was derived")
    materials: str = Field(default="", description="Materials or equipment likely needed")
    summary: str = Field(default="", description="One-line summary of the work to be done")


# ── bookkeeping carried through the graph ────────────────────────────────


class NodeDecision(BaseModel):
    """One line of the audit trail, one per node."""

    node: str
    summary: str
    duration_ms: int | None = None


class RetrievedChunk(BaseModel):
    """A retrieval hit, so any decision can cite its sources. Used from Phase 2.

    `node` records which node performed the retrieval. `evidence` in
    ComplaintState is one flat accumulator shared by every node that retrieves,
    so without this field a chunk's origin is unrecoverable once the reducer
    merges it in alongside everyone else's.
    """

    node: str = Field(description="Name of the node that performed this retrieval")
    source: str = Field(description="Path or identifier of the retrieved document")
    chunk_id: str | None = Field(default=None, description="Identifier of the specific chunk within the source")
    score: float | None = Field(default=None, description="Retrieval relevance score, if available")
    snippet: str = Field(default="", description="Excerpt of the retrieved text")
