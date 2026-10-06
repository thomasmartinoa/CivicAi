"""Does the similarity threshold actually group the same problem?

Phase 2c set `cluster_similarity_threshold = 0.82` and recorded, on its own
carry-forward list, that the number had never been measured against real
embeddings — the unit tests use a bag-of-words fake precisely so the threshold is
not vacuous, which also means they cannot answer this.

This measures it, pair-wise: every pair of golden items sharing a `cluster_group`
is a pair that should be grouped, every other pair should not be. Precision is
"of the pairs it grouped, how many belonged together"; recall is "of the pairs that
belonged together, how many did it find". Pairs rather than whole clusters, because
a detector that splits one true group of three into a pair plus a single is wrong by
one pair, not wholly wrong.

**What this deliberately does not measure.** The golden items carry no coordinates,
so the eval assigns them: items in a group go a few dozen metres apart and
everything else is scattered kilometres away. Geography is therefore held constant
and what is under test is the semantic half — the embedding and the threshold.
Haversine is already covered by unit tests, and inventing plausible coordinates for
a hundred complaints would measure the invention.
"""

import logging
from dataclasses import dataclass
from itertools import combinations

from app.ai.rag.embeddings import Embedder
from app.evals.dataset import GoldenItem, load_golden
from app.services.clustering import Candidate, cluster_candidates
from app.db.base import utcnow

logger = logging.getLogger(__name__)

# One spot per group, far enough apart that no two groups can merge on distance.
_GROUP_ORIGINS = [(12.9716, 77.5946), (13.0827, 77.5877), (12.9141, 77.6101),
                  (13.1986, 77.7066), (12.8449, 77.6631)]
# ~40 m of latitude: inside any sane radius, so distance never decides the outcome.
_WITHIN_GROUP_STEP = 0.00036
# Distractors are spread on a wide arc so none of them lands near a group.
_DISTRACTOR_STEP = 0.02
# ...except the near ones, which are dropped *inside* a group's radius on purpose.
# Without them precision is guaranteed by geometry: a distractor kilometres away
# cannot group whatever its cosine, so a far-only fixture reports precision 1.00
# while testing nothing about the threshold. These sit ~90 m from a group's origin,
# well inside any sane radius, so only semantics can keep them out.
_NEAR_DISTRACTOR_OFFSET = 0.0008
NEAR_DISTRACTORS_PER_GROUP = 2


class _MemoisingEmbedder:
    """Embed each distinct text once, however many thresholds are swept.

    A threshold sweep re-runs the detector over the same texts, and the first
    version of this module re-embedded all of them per threshold: 800 calls for 100
    texts, which walked straight into the free tier's 100-embeddings-per-minute cap.
    The vectors cannot change between thresholds, so they are computed once.
    """

    def __init__(self, embedder: Embedder):
        self._embedder = embedder
        self.model_tag = embedder.model_tag
        self._cache: dict[str, list[float]] = {}
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            self.calls += len(missing)
            for text, vector in zip(missing, self._embedder.embed_documents(missing)):
                self._cache[text] = vector
        return [self._cache[t] for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@dataclass(frozen=True)
class ClusterEvalResult:
    precision: float | None
    recall: float | None
    true_pairs: int
    predicted_pairs: int
    correct_pairs: int
    clusters_found: int
    threshold: float
    radius_km: float
    min_size: int

    @property
    def summary(self) -> str:
        if self.precision is None or self.recall is None:
            return (f"threshold {self.threshold}: nothing to score "
                    f"({self.true_pairs} true pairs, {self.predicted_pairs} predicted)")
        return (f"threshold {self.threshold}: precision {self.precision:.2f}, "
                f"recall {self.recall:.2f} over {self.true_pairs} true pairs "
                f"({self.clusters_found} clusters found)")


def _candidates(items: list[GoldenItem]) -> list[Candidate]:
    """Give every item a position.

    Grouped items go a few dozen metres apart at their group's origin. The first
    few ungrouped items are placed *inside* those same radii — they are different
    problems at the same address, so only the similarity threshold can keep them
    out of the cluster, and they are what makes precision mean anything. The rest
    are scattered kilometres away.
    """
    candidates: list[Candidate] = []
    group_index: dict[str, int] = {}
    within: dict[str, int] = {}

    origins_used: list[tuple[float, float]] = []
    for item in items:
        if not item.cluster_group:
            continue
        if item.cluster_group not in group_index:
            group_index[item.cluster_group] = len(group_index)
            origins_used.append(_GROUP_ORIGINS[group_index[item.cluster_group] % len(_GROUP_ORIGINS)])

    near_slots = [
        (origin[0] + (n + 1) * _NEAR_DISTRACTOR_OFFSET, origin[1])
        for origin in origins_used for n in range(NEAR_DISTRACTORS_PER_GROUP)
    ]
    near_used = 0
    far = 0

    for item in items:
        if item.cluster_group:
            origin = _GROUP_ORIGINS[group_index[item.cluster_group] % len(_GROUP_ORIGINS)]
            offset = within.get(item.cluster_group, 0)
            within[item.cluster_group] = offset + 1
            coords = (origin[0] + offset * _WITHIN_GROUP_STEP, origin[1])
        elif near_used < len(near_slots):
            coords = near_slots[near_used]
            near_used += 1
        else:
            far += 1
            coords = (12.0 + far * _DISTRACTOR_STEP, 76.0 + far * _DISTRACTOR_STEP)
        candidates.append(Candidate(
            id=item.id, text=item.description, coords=coords,
            priority=item.expected_priority or 0, created_at=utcnow(),
            category=item.expected_category.value if item.expected_category else "UNKNOWN",
        ))
    return candidates


# Enough non-duplicates to catch a detector that groups unrelated complaints,
# without embedding the whole set: the free tier allows 100 embeddings a minute and
# the distractors only need to be numerous enough to be a real test.
DEFAULT_DISTRACTORS = 24


def eval_items(items: list[GoldenItem] | None = None,
               max_distractors: int = DEFAULT_DISTRACTORS) -> list[GoldenItem]:
    """Every grouped item, plus a bounded, deterministic set of distractors."""
    items = items if items is not None else load_golden()
    grouped = [i for i in items if i.cluster_group]
    others = sorted((i for i in items if not i.cluster_group), key=lambda i: i.id)
    return grouped + others[:max_distractors]


def evaluate_clustering(*, embedder: Embedder, threshold: float, radius_km: float,
                        min_size: int, items: list[GoldenItem] | None = None) -> ClusterEvalResult:
    """Pair-wise precision and recall for one threshold."""
    items = eval_items(items)
    candidates = _candidates(items)
    groups = {i.id: i.cluster_group for i in items}

    true_pairs = {
        frozenset((a, b)) for a, b in combinations(groups, 2)
        if groups[a] and groups[a] == groups[b]
    }
    clusters = cluster_candidates(candidates, embedder=embedder, radius_km=radius_km,
                                  threshold=threshold, min_size=min_size)
    predicted_pairs = {
        frozenset(pair) for cluster in clusters for pair in combinations(cluster.ids, 2)
    }
    correct = true_pairs & predicted_pairs

    precision = len(correct) / len(predicted_pairs) if predicted_pairs else None
    recall = len(correct) / len(true_pairs) if true_pairs else None
    return ClusterEvalResult(
        precision=precision, recall=recall, true_pairs=len(true_pairs),
        predicted_pairs=len(predicted_pairs), correct_pairs=len(correct),
        clusters_found=len(clusters), threshold=threshold, radius_km=radius_km,
        min_size=min_size,
    )


def sweep_thresholds(*, embedder: Embedder, thresholds: list[float], radius_km: float,
                     min_size: int) -> list[ClusterEvalResult]:
    """The same dataset at several thresholds, so the configured value can be
    defended against its neighbours rather than asserted.

    The embedder is memoised across thresholds: the texts do not change, so the
    whole sweep costs one pass of embeddings rather than one per threshold.
    """
    items = eval_items()
    memoising = _MemoisingEmbedder(embedder)
    results = [evaluate_clustering(embedder=memoising, threshold=t, radius_km=radius_km,
                                   min_size=min_size, items=items) for t in thresholds]
    logger.info("swept %d thresholds with %d embeddings", len(thresholds), memoising.calls)
    return results
