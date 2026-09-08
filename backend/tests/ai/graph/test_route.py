import pytest

from app.ai.graph.nodes.route import route_node, score_contractor
from app.ai.schemas import ClassificationResult, LocationInfo
from app.constants import Category
from app.db.models.core import Contractor, Department, Tenant
from app.services.seed import seed_database


@pytest.fixture
def seeded(db_session):
    seed_database(db_session)
    return db_session


def _state(base_state, **over):
    return {**base_state,
            "classification": ClassificationResult(category=Category.ROADS, confidence=0.9),
            **over}


def test_routes_to_the_department_that_owns_the_category(make_config, base_state, seeded):
    """Read from Department.categories, not a hardcoded dict. v1 declared the
    column, populated it in the seed, and then ignored it."""
    config = make_config(session_factory=lambda: seeded)
    update = route_node(_state(base_state), config)

    assert update["routing"].department_name == "Public Works Department"
    assert update["routing"].department_id is not None


def test_every_category_resolves_to_a_real_department(make_config, base_state, seeded):
    """v1 Bug 3: CONSTRUCTION and SEWAGE mapped to departments never created."""
    config = make_config(session_factory=lambda: seeded)
    for category in Category:
        state = _state(base_state,
                       classification=ClassificationResult(category=category, confidence=0.9))
        update = route_node(state, config)
        assert update["routing"].department_id is not None, f"{category} routed nowhere"


def test_a_specialist_contractor_outranks_a_generalist():
    specialist = Contractor(name="S", specializations=[Category.ROADS.value], rating=3.0)
    generalist = Contractor(name="G", specializations=[], rating=5.0)
    assert score_contractor(specialist, Category.ROADS, None) > score_contractor(generalist, Category.ROADS, None)


def test_a_busy_contractor_is_penalised():
    idle = Contractor(name="I", specializations=[Category.ROADS.value], rating=4.0, active_workload=0)
    busy = Contractor(name="B", specializations=[Category.ROADS.value], rating=4.0, active_workload=8)
    assert score_contractor(idle, Category.ROADS, None) > score_contractor(busy, Category.ROADS, None)


def test_zone_match_breaks_a_tie():
    near = Contractor(name="N", specializations=[Category.ROADS.value], rating=4.0, zone="South Bangalore")
    far = Contractor(name="F", specializations=[Category.ROADS.value], rating=4.0, zone="North Bangalore")
    assert score_contractor(near, Category.ROADS, "south bangalore") > score_contractor(far, Category.ROADS, "south bangalore")


def test_jurisdiction_is_the_finest_level_available(make_config, base_state, seeded):
    from app.constants import JurisdictionLevel

    config = make_config(session_factory=lambda: seeded)
    state = _state(base_state, location=LocationInfo(ward="Jayanagar", district="Bengaluru Urban"))
    assert route_node(state, config)["routing"].jurisdiction_level is JurisdictionLevel.WARD

    state = _state(base_state, location=LocationInfo(district="Bengaluru Urban"))
    assert route_node(state, config)["routing"].jurisdiction_level is JurisdictionLevel.DISTRICT
