from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.schemas import (
    ClassificationResult, Coords, LocationInfo, MediaInsight, MediaRef,
    NodeDecision, RetrievedChunk, RiskAssessment, RoutingDecision,
    ValidationResult, WorkOrderDraft, band_for_score,
)
from app.constants import Category, RiskLevel


def test_classification_rejects_a_category_outside_the_taxonomy():
    """v1 let the model return 'POTHOLES' and wrote it straight to the database."""
    with pytest.raises(ValidationError):
        ClassificationResult(category="POTHOLES", confidence=0.9)


def test_classification_accepts_a_real_category():
    result = ClassificationResult(category="ROADS", confidence=0.9)
    assert result.category is Category.ROADS


def test_confidence_must_be_a_probability():
    """v1 compared `result.get("confidence", 0) < 0.7` with no guarantee it was numeric."""
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            ClassificationResult(category="ROADS", confidence=bad)


def test_confidence_rejects_non_numeric():
    with pytest.raises(ValidationError):
        ClassificationResult(category="ROADS", confidence="high")


def test_priority_score_is_bounded_to_0_100():
    for bad in (-1, 101):
        with pytest.raises(ValidationError):
            RiskAssessment(priority_score=bad, risk_level="high")


def test_risk_factors_are_each_bounded_to_0_25():
    with pytest.raises(ValidationError):
        RiskAssessment(priority_score=50, risk_level="medium", safety_risk=30)


def test_risk_level_must_match_the_score_band():
    """A model that returns score=90 with risk_level='low' is self-contradictory."""
    with pytest.raises(ValidationError):
        RiskAssessment(priority_score=90, risk_level="low")


def test_risk_level_consistent_with_score_is_accepted():
    assert RiskAssessment(priority_score=90, risk_level="critical").risk_level is RiskLevel.CRITICAL


@pytest.mark.parametrize(
    "score,expected",
    [(0, RiskLevel.LOW), (25, RiskLevel.LOW), (26, RiskLevel.MEDIUM), (50, RiskLevel.MEDIUM),
     (51, RiskLevel.HIGH), (75, RiskLevel.HIGH), (76, RiskLevel.CRITICAL), (100, RiskLevel.CRITICAL)],
)
def test_band_for_score_covers_every_boundary(score, expected):
    assert band_for_score(score) is expected


def test_validation_result_defaults_are_empty_not_none():
    result = ValidationResult(is_valid=True)
    assert result.severity_keywords == []
    assert result.what_happened == ""
    assert result.rejection_reason is None


def test_work_order_draft_round_trips_a_datetime():
    draft = WorkOrderDraft(
        sla_hours=4,
        sla_deadline=datetime(2026, 9, 3, tzinfo=timezone.utc),
        estimated_cost=10000.0,
    )
    assert draft.sla_deadline.year == 2026


def test_the_remaining_models_construct_with_minimal_input():
    assert Coords(latitude=12.9, longitude=77.6).latitude == 12.9
    assert MediaRef(file_path="uploads/x.jpg", media_type="image").original_filename is None
    assert MediaInsight(file_path="uploads/x.jpg", media_type="image", text="a pothole").text
    assert LocationInfo().district == ""
    assert RoutingDecision(department_name="Public Works Department",
                           jurisdiction_level="ward").contractor_id is None
    assert NodeDecision(node="classify", summary="ok").duration_ms is None
    assert RetrievedChunk(source="sop_roads.md").score is None
