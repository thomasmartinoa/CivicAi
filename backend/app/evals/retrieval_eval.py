"""Did retrieval find the chunk that actually answers the question?

This is the deterministic half of what Ragas would tell us, and it is here instead
of Ragas on purpose. Ragas computes `context_recall` and `faithfulness` by asking
an LLM, so every metric costs model calls — on a free tier capped at 20
strong-model requests a day, that is the worst possible thing to spend on. Where
the answer is a fact about a document we wrote ourselves, an LLM judge is also
simply the wrong tool: we know which chunk contains the rate for a trench, so
"was it retrieved" is a set-membership question, not a matter of opinion.

Each case names a query the graph really issues, the filters that go with it, and a
substring that only the right chunk contains. Nothing here needs a chat model; the
embedder alone answers it, and the free embedding quota recovers in a minute rather
than a day.

What this cannot do is judge whether a *generated* answer was faithful to what came
back. That genuinely needs a judge, and it stays unmeasured and declared in
`docs/07-evaluation-and-observability.md` rather than guessed at.
"""

import logging
from dataclasses import dataclass, field

from app.ai.rag.embeddings import Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecallCase:
    name: str
    query: str
    filters: dict
    must_contain: str
    """A substring only the chunk that answers the query holds. Chosen from the
    corpus by hand, which is what makes this deterministic."""
    k: int = 3
    why: str = ""


# The cases come from real failures and real node queries, not from imagination.
# `work_order.trench` is the one three live runs got wrong: the rate card holds
# "Excavation and trench reinstatement | CONSTRUCTION | per m³ | ₹900" and the node
# retrieved three rate-card chunks without it, so the model correctly declined to
# price the job.
CASES: list[RecallCase] = [
    RecallCase(
        name="work_order.trench",
        query="unit rates for CONSTRUCTION repair materials and labour",
        filters={"doc_type": "rate_card"},
        must_contain="Excavation and trench reinstatement",
        why="the exact miss observed in three live runs",
    ),
    RecallCase(
        name="work_order.pothole",
        query="unit rates for ROADS repair materials and labour",
        filters={"doc_type": "rate_card"},
        must_contain="Hot-mix asphalt patching",
        why="the commonest work order in the system",
    ),
    RecallCase(
        name="work_order.cluster",
        query="unit rates and grouped work at multiple sites for ROADS",
        filters={"doc_type": "rate_card"},
        # Body text, not the header: headers live in chunk metadata, so matching on
        # one made this case fail while the right chunk was coming back at rank 1.
        must_contain="billed at 70%",
        why="the bulk rule Phase 2c added; a cluster order cites it or invents one",
    ),
    RecallCase(
        name="assess_risk.bands",
        query="priority bands and response windows by risk level",
        filters={"doc_type": "sla_policy"},
        must_contain="4 hours",
        why="the critical window every work order's deadline rests on",
    ),
    RecallCase(
        name="route.roads_ownership",
        query="which department owns ROADS complaints and who escalates",
        filters={"doc_type": "sop", "category": "ROADS"},
        must_contain="Public Works",
        why="routing cites this; a live run cited the Escalation section instead",
    ),
    RecallCase(
        name="route.construction_ownership",
        query="which department owns CONSTRUCTION complaints and who escalates",
        filters={"doc_type": "sop", "category": "CONSTRUCTION"},
        must_contain="Public Works",
    ),
    RecallCase(
        name="investigate.taxonomy",
        query="the contractor dug up the road and left the trench unfilled",
        filters={"doc_type": "taxonomy"},
        # The hand-off sentence itself, not the word "CONSTRUCTION" — which is also
        # a section header, so the case could have passed on any passing mention
        # rather than on the rule the investigate loop actually needs.
        must_contain="excavation left",
        why="the investigate loop's whole purpose is reaching this hand-off rule",
    ),
]


@dataclass
class CaseResult:
    case: RecallCase
    found: bool
    rank: int | None
    """Where the answering chunk came back, 1-based, or None when it did not."""
    retrieved: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def summary(self) -> str:
        if self.error:
            return f"{self.case.name}: could not run ({self.error})"
        if self.found:
            return f"{self.case.name}: found at rank {self.rank} of {self.case.k}"
        return f"{self.case.name}: MISSED — {', '.join(self.retrieved) or 'nothing retrieved'}"


@dataclass
class RecallReport:
    results: list[CaseResult]

    @property
    def recall_at_k(self) -> float | None:
        scored = [r for r in self.results if r.error is None]
        return sum(1 for r in scored if r.found) / len(scored) if scored else None

    @property
    def misses(self) -> list[CaseResult]:
        return [r for r in self.results if r.error is None and not r.found]


def evaluate_retrieval(retriever, *, cases: list[RecallCase] | None = None,
                       fetch_k: int = 200) -> RecallReport:
    """Run every case against a retriever and report recall@k.

    `fetch_k` matches `app/ai/graph/retrieval.py`'s DEFAULT_FETCH_K, because the
    whole point is to reproduce what the nodes actually see rather than a
    best-case search.
    """
    results: list[CaseResult] = []
    for case in cases if cases is not None else CASES:
        try:
            hits = retriever.search(case.query, k=case.k, fetch_k=fetch_k, filters=case.filters)
        except Exception as exc:
            results.append(CaseResult(case=case, found=False, rank=None, error=str(exc)))
            continue

        rank = None
        labels = []
        for position, hit in enumerate(hits, start=1):
            headers = " › ".join(hit.chunk.metadata.get("headers", []))
            labels.append(f"{hit.chunk.source} › {headers}" if headers else hit.chunk.source)
            if rank is None and case.must_contain.lower() in hit.chunk.text.lower():
                rank = position
        results.append(CaseResult(case=case, found=rank is not None, rank=rank, retrieved=labels))
    return RecallReport(results=results)


def build_embedder_free(embedder: Embedder | None = None) -> Embedder:
    """The real embedder unless one is injected. Embeddings are the one paid call
    this module makes, and the free quota is per minute rather than per day."""
    if embedder is not None:
        return embedder
    from app.ai.rag.embeddings import build_embedder

    return build_embedder()
