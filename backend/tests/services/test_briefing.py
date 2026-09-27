"""The daily briefing.

v1's version raised AttributeError on every single run, the enclosing
`except Exception` swallowed it, and every officer briefing ever produced was
the hardcoded template — for the life of the project, with nothing recorded.
`DailyBriefing.is_fallback` exists because of that, and the test that asserts it
is False on the happy path is the one that stops this repeating.
"""

from datetime import timedelta

import pytest

from app.ai.schemas import BriefingNarrative
from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant
from app.db.models.workflow import DailyBriefing, Escalation, WorkOrder
from app.services.briefing import fallback_narrative, gather_stats, generate_briefing
from app.services.seed import seed_database
from tests.ai.graph.conftest import raises, returns
from tests.ai.graph.test_retrieval import FakeRetriever, _hit


@pytest.fixture
def tenant(db_session):
    return seed_database(db_session)["tenant_id"]


def _complaint(db_session, tenant_id, *, status="assigned", hours_ago=1, tracking=None):
    from uuid import uuid4

    complaint = Complaint(
        tracking_id=tracking or f"CIV-{uuid4().hex[:8].upper()}", tenant_id=tenant_id,
        citizen_email="a@b.com", description="huge pothole on MG Road", category="ROADS",
        risk_level="high", status=status, created_at=utcnow() - timedelta(hours=hours_ago),
    )
    db_session.add(complaint)
    db_session.flush()
    return complaint


def _policy():
    return FakeRetriever([_hit("High complaints are responded to within 24 hours.",
                               "sla_policy.md", ["SLA Policy", "Response windows"])])


def _narrative(summary="Four new reports, two resolved; the MG Road cluster is the priority."):
    return returns(BriefingNarrative(summary=summary,
                                     priorities=["Clear the MG Road cluster before 18:00"],
                                     citations=["sla_policy.md › SLA Policy › Response windows"]))


def _generate(db_session, tenant_id=None, **over):
    kwargs = dict(session_factory=lambda: db_session, tenant_id=tenant_id,
                  chain=_narrative(), retriever=_policy())
    kwargs.update(over)
    return generate_briefing(**kwargs)


def test_a_real_briefing_is_not_marked_as_a_fallback(db_session, tenant):
    """The assertion v1 never had."""
    for _ in range(4):
        _complaint(db_session, tenant)
    db_session.commit()

    row = _generate(db_session, tenant)
    assert row.is_fallback is False
    assert "MG Road" in row.narrative
    assert "Clear the MG Road cluster before 18:00" in row.narrative
    assert row.new_complaints == 4


def test_a_broken_chain_falls_back_visibly(db_session, tenant, caplog):
    """v1's exact failure: an AttributeError inside the chain. The difference is
    that the row now says so and the log says so."""
    _complaint(db_session, tenant)
    db_session.commit()

    with caplog.at_level("WARNING"):
        row = _generate(db_session, tenant, chain=raises(AttributeError("_has_api_key")))
    assert row.is_fallback is True
    assert "1" in row.narrative, "the fallback must still carry the day's numbers"
    assert "briefing" in caplog.text.lower()


def test_a_missing_index_does_not_make_it_a_fallback(db_session, tenant):
    """Retrieval is a soft dependency: an ungrounded briefing is still a real
    briefing, unlike one the model never wrote."""
    _complaint(db_session, tenant)
    db_session.commit()
    row = _generate(db_session, tenant, retriever=None)
    assert row.is_fallback is False


def test_the_chain_sees_the_numbers_and_the_policy_as_evidence(db_session, tenant):
    from langchain_core.runnables import RunnableLambda

    seen = {}

    def capture(payload):
        seen.update(payload)
        return BriefingNarrative(summary="ok", priorities=[], citations=[])

    _complaint(db_session, tenant)
    db_session.commit()
    _generate(db_session, tenant, chain=RunnableLambda(capture))
    assert "[1] sla_policy.md › SLA Policy › Response windows" in seen["evidence"]
    assert "1" in seen["stats_table"]
    assert seen["date"]


def test_one_row_per_tenant_per_day(db_session, tenant):
    """The job runs at 08:00; a retry or a manual run must not add a second
    briefing for the same morning."""
    _complaint(db_session, tenant)
    db_session.commit()
    first = _generate(db_session, tenant)
    second = _generate(db_session, tenant, chain=_narrative("A revised summary."))
    assert first.id == second.id
    assert db_session.query(DailyBriefing).count() == 1
    assert "revised" in db_session.query(DailyBriefing).one().narrative


def test_every_tenant_gets_its_own_briefing(db_session, tenant):
    other = Tenant(name="Mysuru City Corporation", config={})
    db_session.add(other)
    db_session.flush()
    _complaint(db_session, tenant)
    _complaint(db_session, other.id)
    _complaint(db_session, other.id)
    db_session.commit()

    generate_briefing(session_factory=lambda: db_session, chain=_narrative(), retriever=_policy())
    rows = {r.tenant_id: r for r in db_session.query(DailyBriefing).all()}
    assert set(rows) == {tenant, other.id}
    assert rows[tenant].new_complaints == 1
    assert rows[other.id].new_complaints == 2


def test_stats_count_only_the_requested_day_and_tenant(db_session, tenant):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    _complaint(db_session, tenant, hours_ago=1)
    _complaint(db_session, tenant, hours_ago=30)          # yesterday
    _complaint(db_session, other.id, hours_ago=1)         # another tenant
    db_session.commit()

    stats = gather_stats(db_session, tenant_id=tenant, day=utcnow().date())
    assert stats.new_complaints == 1


def test_resolved_escalated_and_clustered_are_counted(db_session, tenant):
    resolved = _complaint(db_session, tenant, status="resolved")
    resolved.updated_at = utcnow()
    open_one = _complaint(db_session, tenant)
    db_session.add(Escalation(complaint_id=open_one.id, from_level="ward", to_level="block",
                              reason="SLA breached", escalated_at=utcnow()))
    db_session.add(WorkOrder(complaint_id=open_one.id, tenant_id=tenant, status="assigned",
                             is_cluster=True, cluster_size=3, sla_hours=24, created_at=utcnow()))
    db_session.commit()

    stats = gather_stats(db_session, tenant_id=tenant, day=utcnow().date())
    assert stats.resolved_today == 1
    assert stats.escalations_today == 1
    assert stats.clusters_detected == 1


def test_sla_at_risk_uses_the_monitor_band_not_its_own(db_session, tenant):
    """The warning band is defined once, in services/sla.py."""
    from app.services.sla import WARNING_AT

    safe = _complaint(db_session, tenant)
    at_risk = _complaint(db_session, tenant)
    created = utcnow() - timedelta(hours=20)
    db_session.add(WorkOrder(complaint_id=safe.id, tenant_id=tenant, status="assigned", sla_hours=24,
                             created_at=utcnow(), sla_deadline=utcnow() + timedelta(hours=24)))
    db_session.add(WorkOrder(complaint_id=at_risk.id, tenant_id=tenant, status="assigned", sla_hours=24,
                             created_at=created, sla_deadline=created + timedelta(hours=24)))
    db_session.commit()

    stats = gather_stats(db_session, tenant_id=tenant, day=utcnow().date())
    assert stats.sla_at_risk == 1
    assert 0 < WARNING_AT < 1


def test_the_fallback_text_states_every_number(db_session, tenant):
    """It is what an officer reads when the model is down, so it must be useful
    rather than an apology."""
    stats = gather_stats(db_session, tenant_id=tenant, day=utcnow().date())
    text = fallback_narrative(stats)
    for value in (stats.new_complaints, stats.resolved_today, stats.sla_at_risk,
                  stats.escalations_today, stats.clusters_detected):
        assert str(value) in text
