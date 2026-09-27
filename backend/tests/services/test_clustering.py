"""Semantic clustering, tested without a database or a model.

v1 bucketed by `category|round(lat,2)|round(lng,2)`, so two reports of the same
collapsed road grouped only if the classifier gave them the same label *and*
their coordinates rounded into the same cell. These tests pin the two things
that replaced it: distance is continuous, and matching is on meaning.
"""

import hashlib
from datetime import timedelta

import numpy as np
import pytest

from app.ai.rag.embeddings import EMBEDDING_DIM, FakeEmbedder
from app.db.base import utcnow
from app.services.clustering import Candidate, cluster_candidates, cosine, haversine_km

# A few coordinates in Bengaluru, metres apart, so "within 500 m" is a real test.
MG_ROAD = (12.9716, 77.5946)
MG_ROAD_50M = (12.9720, 77.5948)
MG_ROAD_200M = (12.9734, 77.5946)
YELAHANKA = (13.1007, 77.5963)  # ~14 km north


class WordEmbedder:
    """A tiny bag-of-words embedder, so overlapping wording really does score
    a high cosine.

    FakeEmbedder hashes whole strings: only *identical* text is similar under
    it, which makes a similarity threshold vacuous. This maps each text onto a
    fixed vocabulary so "hole in the road" and "the road has a hole" are close
    and "streetlight is dark" is not. Deterministic and offline. Whether 0.82
    is the right threshold on real prose is a Phase 3 eval question, not
    something any fake can answer.
    """

    model_tag = f"words@{EMBEDDING_DIM}"
    VOCAB = ("road", "pothole", "hole", "trench", "surface", "caved", "dug",
             "streetlight", "dark", "water", "leak", "mg", "school", "junction")

    def embed_query(self, text: str) -> list[float]:
        words = set(text.lower().replace(",", " ").replace(".", " ").split())
        vector = np.zeros(EMBEDDING_DIM, dtype="float32")
        for index, term in enumerate(self.VOCAB):
            if term in words:
                vector[index] = 1.0
        if not vector.any():
            # Unknown wording still needs a stable, non-zero vector, or cosine
            # is undefined; hash it into the tail of the space.
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
            vector[len(self.VOCAB):] = np.random.default_rng(seed).standard_normal(
                EMBEDDING_DIM - len(self.VOCAB)
            )
        return (vector / np.linalg.norm(vector)).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


def _candidate(text, coords, *, category="ROADS", priority=50, minutes_ago=0, id=None):
    return Candidate(
        id=id or f"c-{abs(hash((text, coords))) % 10**6}",
        text=text,
        coords=coords,
        priority=priority,
        created_at=utcnow() - timedelta(minutes=minutes_ago),
        category=category,
    )


def _cluster(candidates, *, radius_km=0.5, threshold=0.6, min_size=3, embedder=None):
    return cluster_candidates(candidates, embedder=embedder or WordEmbedder(),
                              radius_km=radius_km, threshold=threshold, min_size=min_size)


def test_haversine_matches_a_known_distance():
    """Bangalore City station to Cantonment, about 3 km apart."""
    assert haversine_km((12.9767, 77.5713), (12.9989, 77.5905)) == pytest.approx(3.0, abs=1.0)
    assert haversine_km(MG_ROAD, MG_ROAD) == 0.0
    assert haversine_km(MG_ROAD, YELAHANKA) == pytest.approx(14.4, abs=1.5)


def test_cosine_is_one_for_identical_text_and_low_for_unrelated():
    embedder = WordEmbedder()
    road = np.asarray(embedder.embed_query("hole in the road"))
    same = np.asarray(embedder.embed_query("the road has a hole"))
    lamp = np.asarray(embedder.embed_query("streetlight is dark"))
    assert cosine(road, same) == pytest.approx(1.0, abs=0.01)
    assert cosine(road, lamp) < 0.3


def test_reports_of_the_same_problem_group_even_across_categories():
    """The point of the rewrite: v1 required identical category labels."""
    # threshold=0.5 because WordEmbedder scores overlap crudely -- three words
    # in common out of four is 0.5 under it. What a real embedder gives these
    # three sentences is a Phase 3 eval question; the behaviour under test is
    # that differing *categories* do not prevent grouping.
    clusters = _cluster([
        _candidate("the contractor dug up mg road and left a trench", MG_ROAD, category="CONSTRUCTION"),
        _candidate("huge hole in the mg road surface", MG_ROAD_50M, category="ROADS", priority=80),
        _candidate("mg road surface caved in near the junction", MG_ROAD_200M, category="ROADS"),
    ], threshold=0.5)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.size == 3
    assert cluster.lead.priority == 80, "the most urgent report leads"
    assert cluster.category == "ROADS", "the cluster inherits the lead's category, so routing has one"


def test_distance_beats_similarity():
    """Identical wording 14 km apart is two problems, not one."""
    text = "huge hole in the mg road surface"
    clusters = _cluster([
        _candidate(text, MG_ROAD, id="near-1"),
        _candidate(text, MG_ROAD_50M, id="near-2"),
        _candidate(text, YELAHANKA, id="far-1"),
    ], min_size=2)
    assert len(clusters) == 1
    assert {c.id for c in clusters[0].members} == {"near-1", "near-2"}


def test_unrelated_problems_at_one_spot_do_not_group():
    """Same place, different job: one crew cannot fix both."""
    clusters = _cluster([
        _candidate("huge hole in the mg road surface", MG_ROAD),
        _candidate("streetlight is dark", MG_ROAD_50M, category="ELECTRICITY"),
        _candidate("water leak", MG_ROAD_50M, category="WATER"),
    ], min_size=2)
    assert clusters == []


def test_a_group_below_the_minimum_is_not_a_cluster_and_stays_available():
    """A pair is not a cluster, and its members must remain free for a later
    lead to claim — releasing them is the part a greedy walk gets wrong."""
    text = "huge hole in the mg road surface"
    candidates = [
        _candidate(text, MG_ROAD, priority=90, id="a"),
        _candidate(text, MG_ROAD_50M, priority=80, id="b"),
        _candidate(text, MG_ROAD_200M, priority=70, id="c"),
    ]
    assert _cluster(candidates, min_size=4) == []
    # The same three, with the minimum they do meet, must still group.
    assert _cluster(candidates, min_size=3)[0].size == 3


def test_ordering_is_deterministic_regardless_of_input_order():
    text = "mg road surface caved in"
    a = _candidate(text, MG_ROAD, priority=50, minutes_ago=10, id="a")
    b = _candidate(text, MG_ROAD_50M, priority=50, minutes_ago=30, id="b")
    c = _candidate(text, MG_ROAD_200M, priority=50, minutes_ago=20, id="c")
    first = _cluster([a, b, c])[0]
    second = _cluster([c, a, b])[0]
    assert first.lead.id == second.lead.id == "b", "the oldest wins a priority tie"
    assert [m.id for m in first.members] == [m.id for m in second.members]


def test_the_embedder_is_called_once_for_the_whole_batch():
    """One round trip per tick, not one per pair: this runs against a real
    embedding API in production."""
    class CountingEmbedder(WordEmbedder):
        def __init__(self):
            self.batches = 0

        def embed_documents(self, texts):
            self.batches += 1
            return super().embed_documents(texts)

    embedder = CountingEmbedder()
    _cluster([_candidate("mg road hole", MG_ROAD), _candidate("mg road hole", MG_ROAD_50M),
              _candidate("mg road hole", MG_ROAD_200M)], embedder=embedder)
    assert embedder.batches == 1


def test_an_empty_or_single_candidate_list_is_handled_without_embedding():
    class Exploding:
        model_tag = "no"

        def embed_documents(self, texts):
            raise AssertionError("must not embed")

    assert cluster_candidates([], embedder=Exploding(), radius_km=0.5, threshold=0.6, min_size=3) == []
    single = [_candidate("mg road hole", MG_ROAD)]
    assert cluster_candidates(single, embedder=Exploding(), radius_km=0.5, threshold=0.6, min_size=3) == []


def test_identical_text_still_clusters_under_the_hashing_fake():
    """The production embedder is not the WordEmbedder above, so the algorithm
    must also work when only identical strings are similar."""
    text = "pothole outside the school gate"
    clusters = _cluster([_candidate(text, MG_ROAD, id="a"), _candidate(text, MG_ROAD_50M, id="b"),
                         _candidate(text, MG_ROAD_200M, id="c")],
                        embedder=FakeEmbedder(), threshold=0.95)
    assert len(clusters) == 1 and clusters[0].size == 3


# ── the hourly job ──────────────────────────────────────────────────────────


@pytest.fixture
def tenant(db_session):
    from app.services.seed import seed_database

    return seed_database(db_session)["tenant_id"]


def _stored(db_session, tenant_id, text, coords, *, category="ROADS", risk="high",
            priority=50, status="assigned", tracking=None):
    from uuid import uuid4

    from app.db.models.complaint import Complaint

    complaint = Complaint(
        tracking_id=tracking or f"CIV-{uuid4().hex[:8].upper()}", tenant_id=tenant_id,
        citizen_email="a@b.com", description=text, category=category, risk_level=risk,
        priority_score=priority, status=status, latitude=coords[0], longitude=coords[1],
        district="South Bangalore",
    )
    db_session.add(complaint)
    db_session.flush()
    return complaint


def _three_potholes(db_session, tenant_id):
    text = "huge hole in the mg road surface"
    made = [_stored(db_session, tenant_id, text, c, priority=p)
            for c, p in ((MG_ROAD, 90), (MG_ROAD_50M, 60), (MG_ROAD_200M, 40))]
    db_session.commit()
    return made


def _rate_card():
    from tests.ai.graph.test_retrieval import FakeRetriever, _hit

    return FakeRetriever([_hit("Second and subsequent sites are billed at 70% of labour.",
                               "rate_card.md", ["Municipal Rate Card", "Grouped work at multiple sites"])])


def _estimate(cost=21000.0, basis="3 sites, mobilisation charged once [1]"):
    from app.ai.schemas import CostEstimate
    from tests.ai.graph.conftest import returns

    return returns(CostEstimate(estimated_cost=cost, cost_basis=basis, materials="hot mix"))


def _detect(db_session, **over):
    from app.services.clustering import detect_clusters

    kwargs = dict(session_factory=lambda: db_session, embedder=FakeEmbedder(),
                  cost_chain=_estimate(), retriever=_rate_card(), threshold=0.95)
    kwargs.update(over)
    return detect_clusters(**kwargs)


def test_three_nearby_reports_become_one_grouped_work_order(db_session, tenant):
    from app.db.models.complaint import Complaint
    from app.db.models.workflow import WorkOrder
    from app.services.clustering import ClusterTick

    lead = _three_potholes(db_session, tenant)[0]
    assert _detect(db_session) == ClusterTick(clusters=1, complaints=3)

    db_session.expire_all()
    order = db_session.query(WorkOrder).filter_by(is_cluster=True).one()
    assert order.complaint_id == lead.id, "the highest-priority report leads"
    assert order.cluster_size == 3
    assert order.estimated_cost == 21000.0
    assert "70%" in order.cost_basis or "mobilisation" in order.cost_basis
    assert order.contractor_id is not None, "a cluster still needs a crew"
    assert db_session.query(Complaint).filter_by(cluster_id=lead.id).count() == 3


def test_a_second_tick_clusters_nothing(db_session, tenant):
    from app.db.models.workflow import WorkOrder
    from app.services.clustering import ClusterTick

    _three_potholes(db_session, tenant)
    _detect(db_session)
    assert _detect(db_session) == ClusterTick()
    assert db_session.query(WorkOrder).filter_by(is_cluster=True).count() == 1


def test_clusters_never_span_tenants(db_session, tenant):
    """The SLA monitor's tenant-blindness is already on the carry-forward list;
    this job must not add a second instance of it."""
    from app.db.models.core import Tenant
    from app.services.clustering import ClusterTick

    other = Tenant(name="Mysuru City Corporation", config={})
    db_session.add(other)
    db_session.flush()
    text = "huge hole in the mg road surface"
    _stored(db_session, tenant, text, MG_ROAD)
    _stored(db_session, tenant, text, MG_ROAD_50M)
    _stored(db_session, other.id, text, MG_ROAD_200M)
    db_session.commit()

    assert _detect(db_session, min_size=3) == ClusterTick()
    assert _detect(db_session, min_size=2) == ClusterTick(clusters=1, complaints=2)


def test_the_grouped_window_is_the_most_urgent_members(db_session, tenant):
    """One critical report among mediums pulls the whole cluster onto the
    critical window: the crew makes one trip."""
    from app.constants import DEFAULT_SLA_HOURS, RiskLevel
    from app.db.models.workflow import WorkOrder

    text = "huge hole in the mg road surface"
    _stored(db_session, tenant, text, MG_ROAD, risk="medium", priority=40)
    _stored(db_session, tenant, text, MG_ROAD_50M, risk="critical", priority=90)
    _stored(db_session, tenant, text, MG_ROAD_200M, risk="medium", priority=30)
    db_session.commit()

    _detect(db_session)
    db_session.expire_all()
    order = db_session.query(WorkOrder).filter_by(is_cluster=True).one()
    assert order.sla_hours == DEFAULT_SLA_HOURS[RiskLevel.CRITICAL]
    assert order.sla_deadline is not None


def test_a_failed_cost_chain_still_produces_the_cluster(db_session, tenant):
    """Grounding is a soft dependency here too: the crew still needs the job."""
    from app.db.models.workflow import WorkOrder
    from tests.ai.graph.conftest import raises

    _three_potholes(db_session, tenant)
    assert _detect(db_session, cost_chain=raises(RuntimeError("quota"))).clusters == 1
    db_session.expire_all()
    order = db_session.query(WorkOrder).filter_by(is_cluster=True).one()
    assert order.estimated_cost is None
    assert "quota" in order.cost_basis


def test_resolved_and_rejected_complaints_are_not_clustered(db_session, tenant):
    from app.services.clustering import ClusterTick

    text = "huge hole in the mg road surface"
    _stored(db_session, tenant, text, MG_ROAD, status="resolved")
    _stored(db_session, tenant, text, MG_ROAD_50M, status="rejected")
    _stored(db_session, tenant, text, MG_ROAD_200M, status="assigned")
    db_session.commit()
    assert _detect(db_session, min_size=2) == ClusterTick()


def test_complaints_without_coordinates_are_not_clustered(db_session, tenant):
    """v1 wrote `round(complaint.latitude or 0, 2)`, which put every
    coordinate-less complaint in one bucket in the Gulf of Guinea."""
    from app.db.models.complaint import Complaint
    from app.services.clustering import ClusterTick

    text = "huge hole in the mg road surface"
    for _ in range(3):
        complaint = _stored(db_session, tenant, text, (0.0, 0.0))
        complaint.latitude = None
        complaint.longitude = None
    db_session.commit()
    assert _detect(db_session) == ClusterTick()
    assert db_session.query(Complaint).filter(Complaint.cluster_id.isnot(None)).count() == 0


def test_a_member_keeps_a_work_order_it_already_had(db_session, tenant):
    """Work already dispatched is not deleted; the cluster is recorded and the
    officer reconciles."""
    from app.db.models.workflow import WorkOrder

    lead, member, _ = _three_potholes(db_session, tenant)
    existing = WorkOrder(complaint_id=member.id, tenant_id=tenant, status="assigned", sla_hours=24)
    db_session.add(existing)
    db_session.commit()

    _detect(db_session)
    db_session.expire_all()
    assert db_session.query(WorkOrder).filter_by(complaint_id=member.id).one().is_cluster is False
    assert db_session.query(WorkOrder).filter_by(is_cluster=True).one().complaint_id == lead.id


def test_a_lead_that_already_has_a_work_order_is_not_given_a_second(db_session, tenant):
    """work_orders.complaint_id is unique: inserting blindly would raise."""
    from app.db.models.workflow import WorkOrder

    lead = _three_potholes(db_session, tenant)[0]
    db_session.add(WorkOrder(complaint_id=lead.id, tenant_id=tenant, status="assigned", sla_hours=24))
    db_session.commit()

    tick = _detect(db_session)
    db_session.expire_all()
    orders = db_session.query(WorkOrder).filter_by(complaint_id=lead.id).all()
    assert len(orders) == 1, "the existing order is updated in place, not duplicated"
    assert orders[0].is_cluster is True and orders[0].cluster_size == 3
    assert tick.clusters == 1


def test_the_cluster_contractor_is_scored_against_the_leads_district(db_session, tenant):
    """score_contractor gives a zone bonus, so passing None would quietly pick
    a crew from the wrong side of the city."""
    from app.db.models.core import Contractor
    from app.db.models.workflow import WorkOrder

    _three_potholes(db_session, tenant)  # district "South Bangalore"
    _detect(db_session)
    db_session.expire_all()
    order = db_session.query(WorkOrder).filter_by(is_cluster=True).one()
    contractor = db_session.get(Contractor, order.contractor_id)
    assert contractor.zone == "South Bangalore", (
        "the ROADS contractor in the lead's own zone should win the zone bonus"
    )
