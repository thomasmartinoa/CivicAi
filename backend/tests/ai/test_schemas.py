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


@pytest.mark.parametrize(
    "field", ["category_severity", "population_impact", "safety_risk", "urgency"]
)
def test_risk_factors_are_each_bounded_to_0_25(field):
    with pytest.raises(ValidationError):
        RiskAssessment(priority_score=50, risk_level="medium", **{field: 30})


def test_risk_factors_summing_to_the_score_is_accepted():
    assessment = RiskAssessment(
        priority_score=50, risk_level="medium",
        category_severity=15, population_impact=10, safety_risk=15, urgency=10,
    )
    assert assessment.priority_score == 50


def test_risk_factors_contradicting_the_score_are_rejected():
    """A model returning factors that sum to 60 with priority_score=90 must
    not pass: the score would be wrong and everything downstream (the SLA)
    would be set off it."""
    with pytest.raises(ValidationError):
        RiskAssessment(
            priority_score=90, risk_level="critical",
            category_severity=20, population_impact=20, safety_risk=10, urgency=10,
        )


def test_risk_assessment_without_factors_is_still_accepted():
    """The four factors default to 0, so a RiskAssessment constructed with
    only priority_score and risk_level must not be forced to also supply
    factors that sum correctly (several existing tests do exactly this)."""
    assessment = RiskAssessment(priority_score=50, risk_level="medium")
    assert assessment.category_severity == 0


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


def test_work_order_draft_has_no_sla_deadline_field():
    """The model has no reliable notion of 'now'; Phase 1b computes the
    deadline itself from sla_hours instead of trusting a model timestamp."""
    draft = WorkOrderDraft(sla_hours=4, estimated_cost=10000.0)
    assert not hasattr(draft, "sla_deadline")


def test_work_order_draft_rejects_non_positive_sla_hours():
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            WorkOrderDraft(sla_hours=bad, estimated_cost=10000.0)


def test_work_order_draft_rejects_negative_cost():
    with pytest.raises(ValidationError):
        WorkOrderDraft(sla_hours=4, estimated_cost=-1.0)


def test_the_remaining_models_construct_with_minimal_input():
    assert Coords(latitude=12.9, longitude=77.6).latitude == 12.9
    assert MediaRef(file_path="uploads/x.jpg", media_type="image").original_filename is None
    assert MediaInsight(file_path="uploads/x.jpg", media_type="image", text="a pothole").text
    assert LocationInfo().district == ""
    assert RoutingDecision(department_name="Public Works Department",
                           jurisdiction_level="ward").contractor_id is None
    assert NodeDecision(node="classify", summary="ok").duration_ms is None
    assert RetrievedChunk(node="assess_risk", source="sop_roads.md").score is None
