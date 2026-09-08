"""The object every node reads from and writes to.

Two things here are load-bearing and easy to get wrong:

1. Fields written by parallel nodes carry `Annotated[list[X], operator.add]`.
   Without a reducer, LangGraph raises InvalidUpdateError when the media
   subgraph's fan-out branches both write to the same key.

2. Every Pydantic class reachable from state must appear in
   CHECKPOINT_ALLOWLIST. A class missing from it is deserialized back from the
   checkpoint as a plain dict rather than raising, so the failure surfaces much
   later as an AttributeError on a field access.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.ai.schemas import (
    ClassificationResult, Coords, LocationInfo, MediaInsight, MediaRef,
    NodeDecision, RetrievedChunk, RiskAssessment, RoutingDecision,
    ValidationResult, WorkOrderDraft,
)
from app.constants import Category, RiskLevel


class ComplaintState(TypedDict):
    # ── immutable input ──────────────────────────────────────
    complaint_id: str
    tracking_id: str
    tenant_id: str | None
    raw_description: str
    media: list[MediaRef]
    coords: Coords | None

    # ── written in parallel: reducers required ───────────────
    media_insights: Annotated[list[MediaInsight], operator.add]
    evidence: Annotated[list[RetrievedChunk], operator.add]
    decision_log: Annotated[list[NodeDecision], operator.add]
    errors: Annotated[list[str], operator.add]

    # ── enriched ─────────────────────────────────────────────
    description: str
    location: LocationInfo | None

    # ── AI outputs ───────────────────────────────────────────
    validation: ValidationResult | None
    classification: ClassificationResult | None
    risk: RiskAssessment | None
    routing: RoutingDecision | None
    work_order: WorkOrderDraft | None

    # ── control ──────────────────────────────────────────────
    investigate_turns: int
    terminal_reason: str | None


# Every Pydantic class and enum reachable from ComplaintState. Pass the classes
# themselves: a ("module",) tuple silently allows nothing, and the symptom is a
# dict where a model should be. Enums must be listed too; a missing enum degrades
# to a plain string rather than raising, so state["classification"].category is
# then False if compared with is.
CHECKPOINT_ALLOWLIST: list[type] = [
    ClassificationResult, Coords, LocationInfo, MediaInsight, MediaRef,
    NodeDecision, RetrievedChunk, RiskAssessment, RoutingDecision,
    ValidationResult, WorkOrderDraft,
    Category, RiskLevel,
]


def build_serializer() -> JsonPlusSerializer:
    """The checkpoint serializer, restricted to our own model classes.

    Checkpoint deserialization is a code-execution surface: anyone who can write
    to the checkpoint database can otherwise choose what gets constructed.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_ALLOWLIST)


def initial_state(
    *,
    complaint_id: str,
    tracking_id: str,
    raw_description: str,
    tenant_id: str | None = None,
    media: list[MediaRef] | None = None,
    coords: Coords | None = None,
) -> ComplaintState:
    """Every key populated, so no node ever meets a missing one."""
    return ComplaintState(
        complaint_id=complaint_id,
        tracking_id=tracking_id,
        tenant_id=tenant_id,
        raw_description=raw_description,
        media=media or [],
        coords=coords,
        media_insights=[],
        evidence=[],
        decision_log=[],
        errors=[],
        description=raw_description,
        location=None,
        validation=None,
        classification=None,
        risk=None,
        routing=None,
        work_order=None,
        investigate_turns=0,
        terminal_reason=None,
    )
