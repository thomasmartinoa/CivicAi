from app.ai.graph.nodes.work_order import _BASE_COST, _RISK_MULTIPLIER, SLA_HOURS, work_order_node
from app.ai.schemas import ClassificationResult, RiskAssessment
from app.constants import Category, RiskLevel


def _state(base_state, level, score):
    return {**base_state,
            "classification": ClassificationResult(category=Category.ROADS, confidence=0.9),
            "risk": RiskAssessment(priority_score=score, risk_level=level)}


def test_every_risk_level_has_an_sla():
    assert set(SLA_HOURS) == set(RiskLevel)


def test_every_category_has_a_base_cost():
    """A 13th Category with no entry raises KeyError inside work_order_node,
    which has no try/except, so it would escape the graph and persist nothing."""
    assert set(_BASE_COST) == set(Category)


def test_every_risk_level_has_a_cost_multiplier():
    assert set(_RISK_MULTIPLIER) == set(RiskLevel)


def test_sla_windows_shorten_as_risk_rises():
    assert (SLA_HOURS[RiskLevel.CRITICAL] < SLA_HOURS[RiskLevel.HIGH]
            < SLA_HOURS[RiskLevel.MEDIUM] < SLA_HOURS[RiskLevel.LOW])


def test_the_node_computes_the_window_not_the_model(make_config, base_state):
    """sla_deadline was deliberately removed from WorkOrderDraft: an LLM has no
    reliable notion of 'now'. The node derives the window from the risk band."""
    from app.ai.schemas import WorkOrderDraft

    assert "sla_deadline" not in WorkOrderDraft.model_fields

    update = work_order_node(_state(base_state, RiskLevel.CRITICAL, 90), make_config())
    assert update["work_order"].sla_hours == SLA_HOURS[RiskLevel.CRITICAL]


def test_the_window_tracks_the_risk_band(make_config, base_state):
    for level, score in ((RiskLevel.HIGH, 60), (RiskLevel.LOW, 10)):
        update = work_order_node(_state(base_state, level, score), make_config())
        assert update["work_order"].sla_hours == SLA_HOURS[level]


def test_the_computed_deadline_is_timezone_aware(make_config, base_state):
    """SQLite drops tzinfo on write, so anything comparing against utcnow()
    later must start from an aware value. See app/db/base.py:utcnow. The
    decision_log summary carries the deadline's isoformat(), so an aware
    datetime shows a "+00:00" offset; a naive datetime.utcnow() would not."""
    update = work_order_node(_state(base_state, RiskLevel.HIGH, 60), make_config())
    summary = update["decision_log"][-1].summary
    assert update["work_order"].sla_hours == SLA_HOURS[RiskLevel.HIGH]
    assert "+00:00" in summary
