"""The three things being compared, behind one `predict(item)` interface.

| label      | what it is                                                      |
|------------|-----------------------------------------------------------------|
| `keyword`  | v1's keyword classifier — the "before" column                    |
| `llm_only` | the real chains on the **ungrounded** prompts, no retrievers     |
| `full`     | current prompts, policy and cases retrieval                      |

`llm_only` is the column that matters. Phases 2a–2c built and grounded a
retrieval stack on the assumption that it helps, and nothing has tested that
assumption. This configuration is a well-prompted model with no evidence at all,
using the `classify` v1 and `assess_risk` v1 prompts the registry has kept
registered since Phase 2b for precisely this purpose. If it wins a category, that
is a finding to publish, not to bury.

Two rules hold for all three:

- **No semantic cache.** A hit would make latency and token counts fiction, and
  `cache_for` keys on (prompt, version) — which does not separate `llm_only` from
  `full`, since they share the `validate` prompt.
- **No database writes.** The nodes are invoked directly with a hand-built state
  rather than through `run_complaint`, so a hundred-item sweep leaves nothing in
  the operator's tables. `route`'s department lookup is a read.

The nodes themselves are used, not the chains, so every soft-failure path the
application relies on is exercised by the eval too.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.ai.graph.deps import GraphDeps, to_configurable
from app.ai.graph.state import ComplaintState, initial_state
from app.ai.schemas import RetrievedChunk
from app.constants import CATEGORY_DEPARTMENT, Category, RiskLevel
from app.evals.dataset import GoldenItem

logger = logging.getLogger(__name__)

# The tenant a prediction claims to belong to. Nothing is written, but
# assess_risk scopes precedent retrieval by tenant and route fails closed
# without one, so the state needs a value.
EVAL_TENANT_ID = "eval-tenant"


@dataclass
class Prediction:
    """What one configuration made of one item.

    `None` means "did not produce this", and the report distinguishes it from a
    wrong answer: `valid=None` after a model outage is not the same claim as
    `valid=False`, which is what v1 conflated.
    """

    valid: bool | None = None
    category: Category | None = None
    department: str | None = None
    risk_band: RiskLevel | None = None
    priority: int | None = None
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    evidence: list[RetrievedChunk] = field(default_factory=list)
    error: str | None = None


class Configuration(Protocol):
    label: str

    def predict(self, item: GoldenItem) -> Prediction: ...


def _department_for(category: Category | None) -> str | None:
    """The owning department for a category.

    One lookup for all three configurations, so the routing column measures the
    same thing in each. Note what this implies and what the report must say: in
    v2 the seeded `Department` rows are built from `CATEGORY_DEPARTMENT`, so
    routing accuracy is a deterministic function of classification accuracy, not
    independent signal. `route_node`'s justification quality is what the Task 7
    judge scores; this is only the assignment.
    """
    return CATEGORY_DEPARTMENT[category] if category else None


class KeywordConfiguration:
    """v1's keyword classifier, the only v1 code left in the repository.

    It has no validity check and no risk model, so those fields stay None and the
    report prints "not applicable" — writing 0 would imply it was measured and
    scored nothing. That it classifies junk confidently is not a bug to fix here;
    it is the finding the invalid-complaint column exists to show.
    """

    label = "keyword"

    def predict(self, item: GoldenItem) -> Prediction:
        from app.evals.baseline import keyword_classify

        started = time.perf_counter()
        result = keyword_classify(item.description)
        elapsed = int((time.perf_counter() - started) * 1000)
        return Prediction(
            valid=True,
            category=result.category,
            department=_department_for(result.category),
            latency_ms=elapsed,
        )


class _GraphConfiguration:
    """Shared machinery for the two LLM columns.

    Runs validate → classify → assess_risk as the graph would, node by node, and
    stops where the graph would stop: a rejected complaint has no category, and a
    node that failed leaves the fields it owns as None with the error recorded.
    """

    label = "override me"
    PROMPT_VERSIONS: dict[str, str] = {}
    USE_RETRIEVERS = False

    def __init__(self, *, deps: GraphDeps | None = None):
        self.deps = deps if deps is not None else self._build_deps()

    def _build_deps(self) -> GraphDeps:
        """The real chains. `cache=None` everywhere — see the module docstring."""
        from app.ai.llm import Task, build_structured
        from app.ai.schemas import ClassificationResult, RiskAssessment, ValidationResult

        version = self.PROMPT_VERSIONS.get
        # One attempt per chain, not three. The sweep is its own retry loop: it
        # logs every failure, aborts on a run of provider errors, and a later
        # --resume retries exactly those items. Stacking the chain's retries on the
        # client's meant a single item cost over two minutes against a 503-ing
        # provider, for a failure the harness was going to record anyway.
        deps = GraphDeps(
            validate_chain=build_structured(Task.VALIDATE, ValidationResult, "validate",
                                            version("validate"), cache=None, retries=1),
            classify_chain=build_structured(Task.CLASSIFY, ClassificationResult, "classify",
                                            version("classify"), cache=None, retries=1),
            risk_chain=build_structured(Task.ASSESS_RISK, RiskAssessment, "assess_risk",
                                        version("assess_risk"), cache=None, retries=1),
        )
        if not self.USE_RETRIEVERS:
            return deps

        from dataclasses import replace

        from app.ai.graph.runner import _cases_retriever_if_present, _POLICY_RETRIEVER

        return replace(deps, policy_retriever=_POLICY_RETRIEVER,
                       cases_retriever=_cases_retriever_if_present())

    def _state(self, item: GoldenItem) -> ComplaintState:
        return initial_state(
            complaint_id=f"eval-{item.id}",
            tracking_id=f"EVAL-{item.id[:8].upper()}",
            tenant_id=EVAL_TENANT_ID,
            raw_description=item.description,
        )

    def predict(self, item: GoldenItem) -> Prediction:
        from app.ai.graph.nodes.assess_risk import assess_risk_node
        from app.ai.graph.nodes.classify import classify_node
        from app.ai.graph.nodes.validate import validate_node

        config = to_configurable(self.deps, thread_id=f"eval-{item.id}")
        state = self._state(item)
        prediction = Prediction()
        evidence: list[RetrievedChunk] = []
        started = time.perf_counter()

        try:
            update = validate_node(state, config)
            state = {**state, **_merged(update, state)}
            if update.get("errors"):
                # Validity is unknown, not False. Conflating a model outage with
                # a rejection is the v1 bug this pipeline was rebuilt to avoid,
                # and the eval must not reintroduce it in its own reporting.
                prediction.error = "; ".join(update["errors"])
                return _finish(prediction, started, evidence)

            validation = update.get("validation")
            prediction.valid = bool(validation.is_valid) if validation else False
            if not prediction.valid:
                return _finish(prediction, started, evidence)

            update = classify_node(state, config)
            state = {**state, **_merged(update, state)}
            evidence += update.get("evidence", [])
            if update.get("errors"):
                prediction.error = "; ".join(update["errors"])
                return _finish(prediction, started, evidence)
            classification = state["classification"]
            prediction.category = classification.category
            prediction.department = _department_for(classification.category)

            update = assess_risk_node(state, config)
            evidence += update.get("evidence", [])
            risk = update.get("risk")
            if risk is not None:
                prediction.risk_band = risk.risk_level
                prediction.priority = risk.priority_score
            errors = [e for e in update.get("errors", []) if "retrieval unavailable" not in e]
            if errors:
                # A missing index is a soft error by design and must not be
                # reported as a failed item; a failed chain must.
                prediction.error = "; ".join(errors)
        except Exception as exc:  # a node raising is a harness bug, not a result
            logger.exception("configuration %s crashed on %s", self.label, item.id)
            prediction.error = f"{type(exc).__name__}: {exc}"

        return _finish(prediction, started, evidence)


def _merged(update: dict, state: ComplaintState) -> dict:
    """Apply a node update the way LangGraph's reducers would.

    The list fields carry `operator.add` in ComplaintState, so they accumulate;
    everything else is replaced. Only the keys the next node reads matter here.
    """
    merged = dict(update)
    for key in ("evidence", "decision_log", "errors", "media_insights"):
        if key in update:
            merged[key] = list(state.get(key, [])) + list(update[key])
    return merged


def _finish(prediction: Prediction, started: float, evidence: list[RetrievedChunk]) -> Prediction:
    prediction.latency_ms = int((time.perf_counter() - started) * 1000)
    prediction.evidence = evidence
    return prediction


class LlmOnlyConfiguration(_GraphConfiguration):
    """A well-prompted model with no evidence. The control for the whole phase."""

    label = "llm_only"
    # The ungrounded versions, kept registered since Phase 2b for this comparison.
    # Using LATEST here would make the two LLM columns differ only in whether
    # evidence appeared in the prompt, not in whether retrieval happened.
    PROMPT_VERSIONS = {"classify": "v1", "assess_risk": "v1"}
    USE_RETRIEVERS = False


class FullConfiguration(_GraphConfiguration):
    """Current prompts, policy and precedent retrieval: v2 as it ships."""

    label = "full"
    PROMPT_VERSIONS: dict[str, str] = {}  # follow LATEST
    USE_RETRIEVERS = True
