"""The officer agent's tools.

Two of these tests are about the shape of the code rather than its behaviour, and
they are the most important ones here: no tool may accept a tenant, and no tool may
change anything. Both properties stop being true the moment someone adds a parameter,
and a test is the only thing that notices.
"""

import inspect
from datetime import timedelta

import pytest

from app.ai.tools.officer import MAX_ROWS, build_officer_tools
from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.core import Contractor, Tenant
from app.db.models.workflow import WorkOrder
from app.services.seed import seed_database


@pytest.fixture
def tenant(db_session):
    return seed_database(db_session)["tenant_id"]


@pytest.fixture
def tools(db_session, tenant):
    return {t.name: t for t in build_officer_tools(lambda: db_session, tenant_id=tenant)}


def _complaint(db_session, tenant_id, **over):
    from uuid import uuid4

    fields = dict(tracking_id=f"CIV-{uuid4().hex[:8].upper()}", tenant_id=tenant_id,
                  citizen_email="a@b.com", description="a blocked drain on 4th Cross",
                  category="WATER", risk_level="high", status="assigned",
                  district="South Bangalore", priority_score=70)
    fields.update(over)
    row = Complaint(**fields)
    db_session.add(row)
    db_session.flush()
    return row


# ── the two structural rules ────────────────────────────────────────────────


def test_no_tool_accepts_a_tenant(tools):
    """The whole security model. A tenant_id parameter is a parameter an LLM fills
    from a context that contains complaint text written by the public, and Phase 3
    measured that 1 in 6 injection items still moves a risk band. A signature that
    cannot express the wrong tenant beats a prompt that asks nicely.
    """
    for name, tool in tools.items():
        assert "tenant_id" not in tool.args, f"{name} exposes tenant_id to the model"
        assert "tenant" not in tool.args, f"{name} exposes a tenant to the model"


def test_no_tool_writes_to_the_database(tools):
    """Read-only until human-in-the-loop approval exists, which the spec defers to
    Phase 7. Until then an LLM does not get to move a municipal work order."""
    import app.ai.tools.officer as module

    source = inspect.getsource(module)
    for forbidden in ("session.add(", "session.commit(", "session.delete(",
                      "session.merge(", ".flush("):
        assert forbidden not in source, f"a tool calls {forbidden}"


# ── tenant scoping, per tool ───────────────────────────────────────────────


def test_every_data_tool_is_scoped_to_its_tenant(db_session, tenant, tools):
    other = Tenant(name="Elsewhere Council", config={})
    db_session.add(other)
    db_session.flush()
    theirs = _complaint(db_session, other.id, tracking_id="CIV-THEIRS99",
                        description="not yours")
    db_session.add(Contractor(tenant_id=other.id, name="Someone Else's Crew",
                              specializations=["WATER"], rating=5.0, active_workload=0))
    mine = _complaint(db_session, tenant, tracking_id="CIV-MINE0001")
    db_session.commit()

    found = tools["find_complaints"].invoke({})
    ids = [c["tracking_id"] for c in found["complaints"]]
    assert "CIV-MINE0001" in ids
    assert "CIV-THEIRS99" not in ids

    # Asking for it by name must not reach across either.
    assert "message" in tools["get_complaint"].invoke({"tracking_id": theirs.tracking_id})

    names = [c["name"] for c in tools["contractor_options"].invoke({"category": "WATER"})["contractors"]]
    assert "Someone Else's Crew" not in names

    assert tools["tenant_statistics"].invoke({})["total_complaints"] == 1
    assert mine.tracking_id == "CIV-MINE0001"


# ── find_complaints ────────────────────────────────────────────────────────


def test_find_complaints_filters_and_is_case_forgiving(db_session, tenant, tools):
    """An LLM will send 'water' and 'Water' as often as 'WATER'."""
    _complaint(db_session, tenant, category="WATER", tracking_id="CIV-WATER001")
    _complaint(db_session, tenant, category="ROADS", tracking_id="CIV-ROADS001")
    db_session.commit()

    for spelling in ("WATER", "water", "Water"):
        found = tools["find_complaints"].invoke({"category": spelling})
        assert [c["tracking_id"] for c in found["complaints"]] == ["CIV-WATER001"], spelling


def test_find_complaints_caps_the_limit(db_session, tenant, tools):
    """A tool that returned a tenant's whole complaint table would blow the context
    window and the quota in one call."""
    for _ in range(MAX_ROWS + 10):
        _complaint(db_session, tenant)
    db_session.commit()

    found = tools["find_complaints"].invoke({"limit": 500})
    assert len(found["complaints"]) == MAX_ROWS


def test_nothing_matching_is_a_message_not_an_exception(tools):
    """A tool that raises ends the agent's turn, so an empty result has to be
    something the model can reason about rather than a crash."""
    found = tools["find_complaints"].invoke({"category": "EDUCATION"})
    assert found["complaints"] == []
    assert "message" in found


# ── get_complaint ──────────────────────────────────────────────────────────


def test_get_complaint_returns_the_stored_justification_and_citations(
        db_session, tenant, tools):
    """The point of the tool: the agent explains what the department actually acted
    on rather than re-deciding it."""
    _complaint(db_session, tenant, tracking_id="CIV-EXPLAIN1",
               routing_justification="Water Board owns WATER [1].",
               evidence=[{"source": "sop_water.md", "headers": ["Water SOP", "Ownership"]}])
    db_session.commit()

    result = tools["get_complaint"].invoke({"tracking_id": "CIV-EXPLAIN1"})
    assert result["routing_justification"] == "Water Board owns WATER [1]."
    assert result["citations"] == ["sop_water.md › Water SOP › Ownership"]


def test_an_unknown_tracking_id_is_a_message(tools):
    result = tools["get_complaint"].invoke({"tracking_id": "CIV-NOTHING9"})
    assert "message" in result


def test_a_tracking_id_is_matched_without_fussing_about_case_or_spaces(
        db_session, tenant, tools):
    _complaint(db_session, tenant, tracking_id="CIV-SLOPPY01")
    db_session.commit()
    result = tools["get_complaint"].invoke({"tracking_id": "  civ-sloppy01 "})
    assert result.get("tracking_id") == "CIV-SLOPPY01"


# ── work_orders_at_risk ────────────────────────────────────────────────────


def test_at_risk_uses_the_same_bands_as_the_escalation_emails(db_session, tenant, tools):
    """If this disagreed with services/sla.py, the agent would tell an officer
    something different from what the contractor was told."""
    from app.services.sla import URGENT_AT

    created = utcnow() - timedelta(hours=20)
    order = WorkOrder(complaint_id=_complaint(db_session, tenant).id, tenant_id=tenant,
                      status="assigned", sla_hours=24, created_at=created,
                      sla_deadline=created + timedelta(hours=24))
    db_session.add(order)
    db_session.commit()

    rows = tools["work_orders_at_risk"].invoke({})["work_orders"]
    assert len(rows) == 1
    assert rows[0]["elapsed_fraction"] >= URGENT_AT
    assert rows[0]["sla_state"] in {"urgent", "breached"}


def test_a_comfortable_order_is_not_reported_as_at_risk(db_session, tenant, tools):
    created = utcnow()
    db_session.add(WorkOrder(complaint_id=_complaint(db_session, tenant).id,
                             tenant_id=tenant, status="assigned", sla_hours=72,
                             created_at=created,
                             sla_deadline=created + timedelta(hours=72)))
    db_session.commit()

    result = tools["work_orders_at_risk"].invoke({})
    assert result["work_orders"] == []
    assert "message" in result


def test_a_completed_order_is_never_at_risk(db_session, tenant, tools):
    """It is finished. Reporting it would send an officer chasing closed work."""
    created = utcnow() - timedelta(hours=40)
    db_session.add(WorkOrder(complaint_id=_complaint(db_session, tenant).id,
                             tenant_id=tenant, status="completed", sla_hours=24,
                             created_at=created, completed_at=utcnow(),
                             sla_deadline=created + timedelta(hours=24)))
    db_session.commit()
    assert tools["work_orders_at_risk"].invoke({})["work_orders"] == []


# ── contractor_options ─────────────────────────────────────────────────────


def test_contractor_options_ranks_with_the_pipelines_own_scoring(db_session, tenant, tools):
    """So the agent's suggestion is the one route would have made."""
    from app.ai.graph.nodes.route import score_contractor
    from app.constants import Category

    rows = tools["contractor_options"].invoke({"category": "WATER"})["contractors"]
    assert rows, "the seed provides contractors"
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)

    contractors = db_session.query(Contractor).filter_by(tenant_id=tenant).all()
    best = max(contractors, key=lambda c: score_contractor(c, Category.WATER, None))
    assert rows[0]["name"] == best.name


def test_an_unknown_category_lists_the_valid_ones(tools):
    """The model guessed wrong; tell it what it may say rather than failing."""
    result = tools["contractor_options"].invoke({"category": "POTHOLES"})
    assert "error" in result
    assert "ROADS" in result["valid"]


# ── tenant_statistics ──────────────────────────────────────────────────────


def test_statistics_pass_through_the_nulls_rather_than_zeroing_them(
        db_session, tenant, tools):
    """Median resolution over nothing resolved is not 0 hours, and an agent that
    read a 0 here would tell an officer the department resolves things instantly."""
    _complaint(db_session, tenant)
    db_session.commit()

    stats = tools["tenant_statistics"].invoke({})
    assert stats["total_complaints"] == 1
    assert stats["median_resolution_hours"] is None
    assert stats["sla_compliance_rate"] is None


# ── search_policy ──────────────────────────────────────────────────────────


def test_policy_search_returns_citations_in_the_graphs_own_format(tools, tenant,
                                                                  db_session):
    """`source › headers`, so a citation the agent quotes can be matched against one
    the pipeline recorded."""
    class FakeHit:
        def __init__(self):
            self.score = 0.9
            self.chunk = type("C", (), {
                "text": "Public Works owns road surface defects.",
                "source": "sop_roads.md",
                "metadata": {"headers": ["Roads SOP", "Ownership"]},
            })()

    class FakeRetriever:
        def search(self, query, k=5):
            return [FakeHit()]

    with_policy = {t.name: t for t in build_officer_tools(
        lambda: db_session, tenant_id=tenant, policy_retriever=FakeRetriever())}
    passages = with_policy["search_policy"].invoke({"query": "who owns potholes"})["passages"]
    assert passages[0]["citation"] == "sop_roads.md › Roads SOP › Ownership"


def test_a_dead_policy_index_does_not_end_the_turn(db_session, tenant):
    """Retrieval is a soft dependency everywhere else in this codebase and here too:
    the agent can still answer from the database."""
    class Broken:
        def search(self, query, k=5):
            raise RuntimeError("the index file is missing")

    broken = {t.name: t for t in build_officer_tools(
        lambda: db_session, tenant_id=tenant, policy_retriever=Broken())}
    result = broken["search_policy"].invoke({"query": "anything"})
    assert result["passages"] == []
    assert "error" in result


def test_no_policy_retriever_configured_is_reported_not_crashed(tools):
    result = tools["search_policy"].invoke({"query": "anything"})
    assert "error" in result
