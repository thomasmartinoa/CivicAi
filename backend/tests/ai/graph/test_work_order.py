from app.ai.graph.nodes.work_order import SLA_HOURS, work_order_node
from app.ai.schemas import ClassificationResult, CostEstimate, RiskAssessment
from app.constants import Category, RiskLevel
from tests.ai.graph.conftest import raises, returns
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


def _state(base_state, level, score):
    return {**base_state,
            "classification": ClassificationResult(category=Category.ROADS, confidence=0.9),
            "risk": RiskAssessment(priority_score=score, risk_level=level)}


def test_every_risk_level_has_an_sla():
    assert set(SLA_HOURS) == set(RiskLevel)


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


def _rate_card():
    return FakeRetriever([
        _hit("| Hot-mix asphalt patching | ROADS | per m² | ₹450 |", "rate_card.md", ["Municipal Rate Card", "Unit rates by item"]),
        _hit("Skilled labour ₹800 per day.", "rate_card.md", ["Municipal Rate Card", "Labour and equipment rates"]),
        _hit("Hot-mix asphalt for surface patching.", "sop_roads.md", ["Roads SOP", "Typical materials and cost drivers"]),
    ])


def test_the_cost_comes_from_the_chain_grounded_in_the_rate_card(make_config, base_state):
    chain = returns(CostEstimate(estimated_cost=6300.0, cost_basis="6 m² asphalt at ₹450 [1] plus one labour day [2]",
                                 materials="hot-mix asphalt, tack coat"))
    update = work_order_node(_state(base_state, RiskLevel.HIGH, 60),
                             make_config(work_order_chain=chain, policy_retriever=_rate_card()))
    draft = update["work_order"]
    assert draft.estimated_cost == 6300.0
    assert "[1]" in draft.cost_basis
    assert draft.materials == "hot-mix asphalt, tack coat"
    assert [c.source for c in update["evidence"]] == ["rate_card.md", "rate_card.md", "sop_roads.md"]
    assert all(c.node == "work_order" for c in update["evidence"])


def test_the_chain_sees_the_evidence_and_the_risk(make_config, base_state):
    seen = {}
    def capture(payload):
        seen.update(payload)
        return CostEstimate(estimated_cost=1.0, cost_basis="x", materials="y")
    from langchain_core.runnables import RunnableLambda
    work_order_node(_state(base_state, RiskLevel.CRITICAL, 90),
                    make_config(work_order_chain=RunnableLambda(capture), policy_retriever=_rate_card()))
    assert seen["category"] == "ROADS"
    assert seen["risk_level"] == "critical"
    assert "[1] rate_card.md › Municipal Rate Card › Unit rates by item" in seen["evidence"]
    assert "pothole" in seen["description"]


def test_a_failed_estimate_still_produces_the_sla_window(make_config, base_state):
    """The window is deterministic and must never wait on the model."""
    update = work_order_node(_state(base_state, RiskLevel.CRITICAL, 90),
                             make_config(work_order_chain=raises(RuntimeError("quota")), policy_retriever=_rate_card()))
    draft = update["work_order"]
    assert draft.sla_hours == SLA_HOURS[RiskLevel.CRITICAL]
    assert draft.estimated_cost is None
    assert draft.cost_basis.startswith("estimate unavailable: ")
    assert update["errors"] == ["work_order: quota"]


def test_no_chain_configured_is_reported_not_raised(make_config, base_state):
    update = work_order_node(_state(base_state, RiskLevel.LOW, 10), make_config())
    assert update["work_order"].estimated_cost is None
    assert update["work_order"].sla_hours == SLA_HOURS[RiskLevel.LOW]
    assert any("work_order_chain" in e for e in update["errors"])


def test_the_placeholder_cost_dicts_are_gone():
    import app.ai.graph.nodes.work_order as module
    assert not hasattr(module, "_BASE_COST") and not hasattr(module, "_RISK_MULTIPLIER")


def test_retrieval_filters_target_the_rate_card_then_the_sop(make_config, base_state):
    retriever = _rate_card()
    work_order_node(_state(base_state, RiskLevel.HIGH, 60),
                    make_config(work_order_chain=returns(CostEstimate(estimated_cost=1, cost_basis="", materials="")),
                                policy_retriever=retriever))
    assert retriever.calls[0]["filters"] == {"doc_type": "rate_card"}
    assert retriever.calls[1]["filters"] == {"doc_type": "sop", "category": "ROADS"}
