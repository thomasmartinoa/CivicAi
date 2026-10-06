"""The clustering eval, offline.

The real measurement needs real embeddings; these tests cover the scoring so the
numbers it later reports can be trusted.
"""

from app.ai.rag.embeddings import FakeEmbedder
from app.evals.clustering_eval import evaluate_clustering, sweep_thresholds
from app.evals.dataset import load_golden
from tests.services.test_clustering import WordEmbedder


# Cosine is never below -1, so this threshold accepts every pair and leaves
# distance as the only filter. Not 0.0: FakeEmbedder's vectors are random, so their
# cosines straddle zero and a 0.0 threshold silently rejects about half the pairs —
# which is how the first version of this test came to expect the wrong answer.
DISTANCE_ONLY = -1.1


def test_distance_alone_finds_every_true_pair_and_a_pile_of_false_ones():
    """The shape the eval has to have to be worth running: with the similarity
    threshold disabled, geometry finds all six true pairs (recall 1.0) and also
    sweeps in the distractors sitting at the same addresses (precision well below
    1.0). Recall measures the radius; precision measures the threshold."""
    result = evaluate_clustering(embedder=FakeEmbedder(), threshold=DISTANCE_ONLY,
                                 radius_km=0.5, min_size=3)
    assert result.true_pairs == 6, "two groups of three is three pairs each"
    assert result.recall == 1.0
    assert result.precision is not None and result.precision < 0.5


def test_an_impossible_threshold_finds_nothing_and_says_so():
    """Precision is None rather than 0.0 when nothing was grouped: the detector
    made no claims, so there is no share of correct claims to report."""
    result = evaluate_clustering(embedder=FakeEmbedder(), threshold=1.01,
                                 radius_km=0.5, min_size=3)
    assert result.clusters_found == 0
    assert result.predicted_pairs == 0
    assert result.precision is None
    assert result.recall == 0.0, "the true pairs still existed and none were found"


def test_the_groups_are_the_only_true_pairs():
    result = evaluate_clustering(embedder=FakeEmbedder(), threshold=DISTANCE_ONLY,
                                 radius_km=0.5, min_size=3)
    groups = {i.cluster_group for i in load_golden() if i.cluster_group}
    assert len(groups) == 2
    assert result.true_pairs == sum(3 for _ in groups)


def test_some_distractors_sit_inside_a_group_so_precision_can_fail():
    """Without in-radius distractors, precision is guaranteed by geometry and the
    number means nothing. With them, disabling the threshold must visibly lose
    precision — proof the fixture can actually punish a bad threshold."""
    result = evaluate_clustering(embedder=FakeEmbedder(), threshold=DISTANCE_ONLY,
                                 radius_km=0.5, min_size=3)
    assert result.precision is not None and result.precision < 1.0, (
        "with the threshold disabled, the near distractors must be swept into the "
        "clusters — if they are not, they are placed too far away to test anything"
    )


def test_near_distractors_are_within_the_radius_and_the_rest_are_not():
    from app.evals.clustering_eval import (
        NEAR_DISTRACTORS_PER_GROUP, _candidates, eval_items,
    )
    from app.services.clustering import haversine_km

    items = eval_items()
    candidates = {c.id: c for c in _candidates(items)}
    grouped_ids = [i.id for i in items if i.cluster_group]
    origins = {candidates[i].coords for i in grouped_ids}
    ungrouped = [candidates[i.id] for i in items if not i.cluster_group]

    inside = [c for c in ungrouped
              if any(haversine_km(c.coords, o) <= 0.5 for o in origins)]
    groups = len({i.cluster_group for i in items if i.cluster_group})
    assert len(inside) == groups * NEAR_DISTRACTORS_PER_GROUP


def test_a_sweep_reports_one_result_per_threshold():
    results = sweep_thresholds(embedder=FakeEmbedder(), thresholds=[DISTANCE_ONLY, 0.5, 1.01],
                               radius_km=0.5, min_size=3)
    assert [r.threshold for r in results] == [DISTANCE_ONLY, 0.5, 1.01]
    assert results[0].recall == 1.0
    assert results[-1].clusters_found == 0


def test_the_summary_is_readable():
    result = evaluate_clustering(embedder=FakeEmbedder(), threshold=DISTANCE_ONLY,
                                 radius_km=0.5, min_size=3)
    assert "precision" in result.summary and "recall" in result.summary
    assert "0.82" not in result.summary or result.threshold == 0.82


def test_a_sweep_embeds_each_text_only_once():
    """The vectors cannot change between thresholds. The first version re-embedded
    everything per threshold and hit the free tier's 100-per-minute embedding cap."""
    from app.evals.clustering_eval import _MemoisingEmbedder, eval_items

    counting = _MemoisingEmbedder(FakeEmbedder())
    items = eval_items()
    for threshold in (DISTANCE_ONLY, 0.5, 0.9, 1.01):
        evaluate_clustering(embedder=counting, threshold=threshold, radius_km=0.5,
                            min_size=3, items=items)
    assert counting.calls == len({i.description for i in items})


def test_the_eval_slice_keeps_every_grouped_item_and_bounds_the_distractors():
    from app.evals.clustering_eval import DEFAULT_DISTRACTORS, eval_items

    items = eval_items()
    grouped = [i for i in items if i.cluster_group]
    assert len(grouped) == len([i for i in load_golden() if i.cluster_group])
    assert len(items) - len(grouped) == DEFAULT_DISTRACTORS
    assert eval_items() == items, "the slice is deterministic"
