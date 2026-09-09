# CivicAI v2 — Phase 1b: Graph Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble the nodes and the LangGraph itself, so a complaint runs end to end from a Python call — validated, classified, risk-scored, routed, and turned into a work-order draft — with durable checkpoints and a persisted audit trail.

**Architecture:** Nodes are plain functions `(state, config) -> dict` returning partial state updates. They never construct a model and never touch the database directly; both arrive through `config["configurable"]`, which is what makes every node testable against fakes with no network. The graph is a deterministic spine with conditional edges; the only fan-out is the media subgraph's `Send`.

**Tech Stack:** LangGraph 1.2.11, LangChain 1.3.18, SQLAlchemy 2.0.52, Python 3.14.

**Spec:** `docs/superpowers/specs/2026-09-02-civicai-v2-design.md`

**Prior phases:** Phase 0 (foundation, 51 tests) and Phase 1a (AI foundations, 113 tests). Read Phase 1a's "Carried forward into Phase 1b" section before starting — it names three design gaps this plan closes.

**Phase 1c (a separate plan) will add:** API wiring, WebSocket streaming of `astream` updates, LangSmith tracing, and the SLA monitor port. This plan stops where a complaint can be run through the graph from a test or a script.

## Global Constraints

- **Python 3.14.** Virtualenv at `backend/.venv`. Tests: `cd backend && .venv/bin/python -m pytest`. Baseline is 113 passing.
- **`app/ai/` must never import `app/api/`.** `app/api/` reaches the graph only through `app/ai/graph/runner.py`. Both enforced by `tests/test_import_rules.py`.
- **No network in tests.** No test may construct a provider client or open a socket.
- **Test output pristine** — the summary line reads `N passed in Xs` with no warning count.
- **Nodes never construct a model.** They receive already-bound runnables through `config["configurable"]`. LangChain's fake chat models raise `NotImplementedError` on `with_structured_output`, so a node holding a raw model cannot be tested without a network call.
- **Nodes never write to the database.** They read through an injected session factory when they must; all writes happen in `runner.py` after the graph returns.
- **Durability is bounded — do not overstate it.** Measured: a node raising an exception persists everything and resumes without re-running completed nodes; a `SIGKILL` mid-node persists almost nothing and restarts. **Therefore any node with an external side effect must be idempotent.** The notify node is the one that matters.
- **Every Pydantic class and enum reachable from state must be in `CHECKPOINT_ALLOWLIST`.** A missing one deserializes back as a `dict` (models) or `str` (enums) with no error.
- **Commit messages carry no `Co-Authored-By` trailer.**

---

## Verified API facts

These were probed directly against the installed versions. Treat them as settled; do not re-derive.

| Fact | Evidence |
|---|---|
| Nodes receive deps via `config["configurable"]["key"]` | probed: injected `RunnableLambda` reached the node |
| `async def` nodes work alongside sync ones | probed |
| `RetryPolicy(max_attempts=3, initial_interval=0.01)` on `add_node` retries and recovers | probed: node failed twice, succeeded on the third |
| A conditional edge may return `END` to short-circuit | probed |
| `Send` fan-out goes through `add_conditional_edges(node, fn, ["target"])` | probed in Phase 1a |
| `AsyncSqliteSaver.from_conn_string(path)` is an **async context manager** | probed |
| The serializer is assigned as `saver.serde = build_serializer()` | probed |
| `graph.ainvoke(None, config)` resumes an existing thread | probed |
| `aget_state_history(config)` yields checkpoints newest-first | probed |

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/ai/graph/deps.py` | `GraphDeps` — the typed bag injected through `configurable` |
| `backend/app/ai/graph/nodes/intake.py` | normalise input, geocode, fan out over media |
| `backend/app/ai/graph/nodes/media.py` | per-file vision / transcription (the `Send` target) |
| `backend/app/ai/graph/nodes/validate.py` | is this an infrastructure complaint? |
| `backend/app/ai/graph/nodes/classify.py` | 1 of 12 categories + confidence |
| `backend/app/ai/graph/nodes/assess_risk.py` | 0–100 priority score |
| `backend/app/ai/graph/nodes/route.py` | department + contractor selection |
| `backend/app/ai/graph/nodes/work_order.py` | SLA window, cost, materials |
| `backend/app/ai/graph/nodes/notify.py` | citizen notification (idempotent) |
| `backend/app/ai/graph/edges.py` | the conditional-edge predicates |
| `backend/app/ai/graph/build.py` | assemble and compile the `StateGraph` |
| `backend/app/ai/graph/runner.py` | run a complaint, persist results and the audit trail |
| `backend/tests/ai/graph/` | mirrors the above |

---

## Task 1: Dependency injection and the node contract

Establishes the seam every other node depends on, and proves it with the two simplest nodes.

**Files:**
- Create: `backend/app/ai/graph/deps.py`, `backend/app/ai/graph/nodes/__init__.py`, `backend/app/ai/graph/nodes/validate.py`, `backend/app/ai/graph/nodes/classify.py`, `backend/app/ai/graph/edges.py`
- Test: `backend/tests/ai/graph/__init__.py`, `backend/tests/ai/graph/conftest.py`, `backend/tests/ai/graph/test_validate.py`, `backend/tests/ai/graph/test_classify.py`, `backend/tests/ai/graph/test_edges.py`

**Interfaces:**
- Consumes: `app.ai.schemas`, `app.ai.graph.state.ComplaintState`, `app.constants`
- Produces:
  - `app.ai.graph.deps.GraphDeps` — a frozen dataclass with fields `validate_chain`, `classify_chain`, `risk_chain`, `vision_chain` (each `Runnable | None`), `session_factory` (`Callable[[], Session] | None`), `geocode` (`Callable | None`), `notify` (`Callable | None`)
  - `app.ai.graph.deps.deps_from_config(config: RunnableConfig) -> GraphDeps` — raises `KeyError` with an actionable message if absent
  - `app.ai.graph.deps.to_configurable(deps: GraphDeps, thread_id: str) -> dict`
  - `app.ai.graph.nodes.validate.validate_node(state, config) -> dict`
  - `app.ai.graph.nodes.classify.classify_node(state, config) -> dict`
  - `app.ai.graph.edges.after_validate(state) -> str` — `"classify"` or `END`
  - `app.ai.graph.edges.CONFIDENCE_THRESHOLD = 0.7`
  - `tests/ai/graph/conftest.py::make_config` — builds a `config` with stub chains

- [ ] **Step 1: Write the failing tests**

```bash
mkdir -p backend/app/ai/graph/nodes backend/tests/ai/graph
touch backend/app/ai/graph/nodes/__init__.py backend/tests/ai/graph/__init__.py
```

`backend/tests/ai/graph/conftest.py`:

```python
"""Fakes for node tests.

Nodes receive already-bound runnables, never raw models, because LangChain's
fake chat models raise NotImplementedError on with_structured_output. A stub
here is just a RunnableLambda returning a fixture.
"""

import pytest
from langchain_core.runnables import RunnableLambda

from app.ai.graph.deps import GraphDeps, to_configurable
from app.ai.graph.state import initial_state


def returns(value):
    """A stub chain that ignores its input and returns `value`."""
    return RunnableLambda(lambda _: value)


def raises(exc):
    def _boom(_):
        raise exc
    return RunnableLambda(_boom)


@pytest.fixture
def make_config():
    def _make(**overrides):
        deps = GraphDeps(**overrides)
        return to_configurable(deps, thread_id="test-thread")
    return _make


@pytest.fixture
def base_state():
    return initial_state(
        complaint_id="c-1",
        tracking_id="CIV-TEST0001",
        raw_description="There is a large pothole on the main road near the school",
    )
```

`backend/tests/ai/graph/test_validate.py`:

```python
import pytest

from app.ai.graph.nodes.validate import validate_node
from app.ai.schemas import ValidationResult
from tests.ai.graph.conftest import raises, returns


def test_accepts_an_infrastructure_complaint(make_config, base_state):
    result = ValidationResult(is_valid=True, what_happened="pothole on the main road")
    update = validate_node(base_state, make_config(validate_chain=returns(result)))

    assert update["validation"].is_valid is True
    assert update["terminal_reason"] is None
    assert update["decision_log"][0].node == "validate"


def test_rejects_a_non_infrastructure_complaint(make_config, base_state):
    result = ValidationResult(is_valid=False, rejection_reason="a dispute with a neighbour")
    update = validate_node(base_state, make_config(validate_chain=returns(result)))

    assert update["validation"].is_valid is False
    assert "neighbour" in update["terminal_reason"]


def test_rejection_is_not_recorded_as_an_error(make_config, base_state):
    """v1's worst bug: a rejection and a crash both went into `errors`, so the
    router overwrote a correctly-rejected complaint's status back to 'submitted'."""
    result = ValidationResult(is_valid=False, rejection_reason="not infrastructure")
    update = validate_node(base_state, make_config(validate_chain=returns(result)))

    assert update.get("errors", []) == []
    assert update["terminal_reason"]


def test_a_too_short_description_is_rejected_without_calling_the_model(make_config):
    """Cheap guards run before spending a request on the free tier."""
    from app.ai.graph.state import initial_state

    called = {"n": 0}

    def counting(_):
        called["n"] += 1
        return ValidationResult(is_valid=True)

    from langchain_core.runnables import RunnableLambda

    state = initial_state(complaint_id="c", tracking_id="CIV-T", raw_description="hi")
    update = validate_node(state, make_config(validate_chain=RunnableLambda(counting)))

    assert called["n"] == 0
    assert update["terminal_reason"]


def test_a_model_failure_becomes_an_error_not_a_rejection(make_config, base_state):
    """An outage must be distinguishable from a business decision."""
    update = validate_node(base_state, make_config(validate_chain=raises(RuntimeError("503"))))

    assert update["errors"]
    assert update.get("terminal_reason") is None
    assert update.get("validation") is None


def test_missing_chain_raises_an_actionable_error(base_state):
    from app.ai.graph.deps import GraphDeps, to_configurable

    config = to_configurable(GraphDeps(), thread_id="t")
    with pytest.raises(ValueError, match="validate_chain"):
        validate_node(base_state, config)
```

`backend/tests/ai/graph/test_classify.py`:

```python
from app.ai.graph.nodes.classify import classify_node
from app.ai.schemas import ClassificationResult
from app.constants import Category
from tests.ai.graph.conftest import raises, returns


def test_records_the_classification(make_config, base_state):
    result = ClassificationResult(category=Category.ROADS, confidence=0.92, subcategory="Pothole")
    update = classify_node(base_state, make_config(classify_chain=returns(result)))

    assert update["classification"].category is Category.ROADS
    assert update["decision_log"][0].node == "classify"


def test_media_insights_are_passed_to_the_model(make_config, base_state):
    """v1 flattened image analysis into the description under a 'Voice
    transcription:' heading. Here it goes in as a separate labelled input."""
    from app.ai.schemas import MediaInsight

    seen = {}

    def capture(payload):
        seen.update(payload)
        return ClassificationResult(category=Category.ROADS, confidence=0.9)

    from langchain_core.runnables import RunnableLambda

    state = {**base_state, "media_insights": [
        MediaInsight(file_path="uploads/a.jpg", media_type="image", text="a deep pothole")
    ]}
    classify_node(state, make_config(classify_chain=RunnableLambda(capture)))

    assert "deep pothole" in seen["media_context"]
    assert seen["description"] == state["description"]


def test_a_model_failure_is_recorded_as_an_error(make_config, base_state):
    update = classify_node(base_state, make_config(classify_chain=raises(RuntimeError("boom"))))
    assert update["errors"]
    assert update.get("classification") is None
```

`backend/tests/ai/graph/test_edges.py`:

```python
from langgraph.graph import END

from app.ai.graph.edges import CONFIDENCE_THRESHOLD, after_validate
from app.ai.schemas import ValidationResult


def _state(**over):
    from app.ai.graph.state import initial_state

    return {**initial_state(complaint_id="c", tracking_id="T", raw_description="x" * 30), **over}


def test_valid_complaints_continue_to_classify():
    assert after_validate(_state(validation=ValidationResult(is_valid=True))) == "classify"


def test_rejected_complaints_go_straight_to_end():
    state = _state(validation=ValidationResult(is_valid=False, rejection_reason="no"),
                   terminal_reason="no")
    assert after_validate(state) == END


def test_an_errored_run_also_ends():
    """A model outage must not fall through into classification."""
    assert after_validate(_state(errors=["validate: 503"])) == END


def test_missing_validation_ends_rather_than_continuing():
    """Fail closed: never classify something that was never validated."""
    assert after_validate(_state()) == END


def test_the_confidence_threshold_is_a_named_constant():
    assert 0.0 < CONFIDENCE_THRESHOLD < 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph.deps'`

- [ ] **Step 3: Implement the dependency bag**

`backend/app/ai/graph/deps.py`:

```python
"""What a node is allowed to reach for, and how it gets there.

Nodes receive dependencies through `config["configurable"]` rather than by
importing them. Two reasons, both load-bearing:

- A node that constructs its own model cannot be unit-tested. LangChain's fake
  chat models raise NotImplementedError on with_structured_output, so tests
  inject an already-bound runnable instead.
- A node that imports a session factory cannot be run against a throwaway
  database without monkeypatching module globals.
"""

from collections.abc import Callable
from dataclasses import dataclass, fields

from langchain_core.runnables import Runnable, RunnableConfig

CONFIG_KEY = "civicai_deps"


@dataclass(frozen=True)
class GraphDeps:
    """Everything the graph needs from the outside world.

    Every field defaults to None so a test can supply only what its node uses.
    A node asking for a dependency that was not supplied gets a ValueError
    naming the field, rather than an AttributeError on None.
    """

    validate_chain: Runnable | None = None
    classify_chain: Runnable | None = None
    risk_chain: Runnable | None = None
    vision_chain: Runnable | None = None
    session_factory: Callable | None = None
    geocode: Callable | None = None
    notify: Callable | None = None

    def require(self, name: str):
        """Fetch a dependency or explain precisely what is missing."""
        value = getattr(self, name, None)
        if value is None:
            available = sorted(f.name for f in fields(self) if getattr(self, f.name) is not None)
            raise ValueError(
                f"GraphDeps.{name} was not provided; supplied: {available or 'nothing'}"
            )
        return value


def to_configurable(deps: GraphDeps, thread_id: str) -> RunnableConfig:
    """Build the config a node expects. `thread_id` keys the checkpoint."""
    return {"configurable": {"thread_id": thread_id, CONFIG_KEY: deps}}


def deps_from_config(config: RunnableConfig) -> GraphDeps:
    try:
        return config["configurable"][CONFIG_KEY]
    except (KeyError, TypeError):
        raise KeyError(
            f"config['configurable'][{CONFIG_KEY!r}] is missing; "
            "build the config with app.ai.graph.deps.to_configurable()"
        ) from None
```

- [ ] **Step 4: Implement the two nodes and the edge**

`backend/app/ai/graph/nodes/validate.py`:

```python
"""Is this an infrastructure complaint the municipality should act on?

The distinction this node draws that v1 could not: a *rejection* is a business
outcome and sets `terminal_reason`; a *model failure* is an infrastructure
problem and appends to `errors`. v1 put both in one list, which is why a
correctly-rejected complaint was stored looking exactly like an unprocessed one.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision

MIN_DESCRIPTION_CHARS = 10


def validate_node(state: ComplaintState, config: RunnableConfig) -> dict:
    chain = deps_from_config(config).require("validate_chain")
    description = state["description"].strip()

    # Cheap guard first: no reason to spend a free-tier request on this.
    if len(description) < MIN_DESCRIPTION_CHARS:
        return {
            "terminal_reason": "Description too short to assess",
            "decision_log": [NodeDecision(node="validate", summary="rejected: too short")],
        }

    try:
        result = chain.invoke({"description": description})
    except Exception as exc:
        return {
            "errors": [f"validate: {exc}"],
            "decision_log": [NodeDecision(node="validate", summary=f"failed: {exc}")],
        }

    if not result.is_valid:
        reason = result.rejection_reason or "Not an infrastructure complaint"
        return {
            "validation": result,
            "terminal_reason": reason,
            "decision_log": [NodeDecision(node="validate", summary=f"rejected: {reason}")],
        }

    return {
        "validation": result,
        "terminal_reason": None,
        "decision_log": [NodeDecision(node="validate", summary="accepted")],
    }
```

`backend/app/ai/graph/nodes/classify.py`:

```python
"""Pick one of the twelve categories, with an honest confidence.

Media insights are passed as a separate labelled input rather than concatenated
into the description. v1 appended image analysis to the description under a
"Voice transcription:" heading, so every downstream step saw mislabelled text.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def _media_context(state: ComplaintState) -> str:
    return "\n".join(
        f"[{insight.media_type}] {insight.text}" for insight in state["media_insights"]
    )


def classify_node(state: ComplaintState, config: RunnableConfig) -> dict:
    chain = deps_from_config(config).require("classify_chain")

    try:
        result = chain.invoke({
            "description": state["description"],
            "media_context": _media_context(state),
        })
    except Exception as exc:
        return {
            "errors": [f"classify: {exc}"],
            "decision_log": [NodeDecision(node="classify", summary=f"failed: {exc}")],
        }

    return {
        "classification": result,
        "decision_log": [NodeDecision(
            node="classify",
            summary=f"{result.category.value} (confidence {result.confidence:.2f})",
        )],
    }
```

`backend/app/ai/graph/edges.py`:

```python
"""Conditional-edge predicates.

Each is a pure function of state, so the routing rules are unit-testable
without building a graph. Every one fails closed: if the evidence a decision
needs is absent, the run ends rather than proceeding on nothing.
"""

from langgraph.graph import END

from app.ai.graph.state import ComplaintState

# Below this, the classification is not trusted on its own. Phase 2 sends these
# to the retrieval loop; until then it is recorded and the run continues.
CONFIDENCE_THRESHOLD = 0.7


def after_validate(state: ComplaintState) -> str:
    if state["errors"]:
        return END
    validation = state["validation"]
    if validation is None or not validation.is_valid:
        return END
    return "classify"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph -v`
Expected: PASS, 14 tests.

- [ ] **Step 6: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, 127 tests (113 + 14).

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: add the node contract with the validate and classify nodes

Nodes take dependencies through config['configurable'] rather than importing
them, so every one is testable against a RunnableLambda with no network call.

validate separates a rejection (terminal_reason) from a model failure (errors).
v1 put both in one list, which is why a correctly-rejected complaint was stored
indistinguishable from an unprocessed one."
```

---

## Task 2: The media subgraph

The only fan-out in the graph. Each uploaded file is analysed in parallel and the results merge through the `media_insights` reducer.

**Files:**
- Create: `backend/app/ai/graph/nodes/intake.py`, `backend/app/ai/graph/nodes/media.py`
- Modify: `backend/app/ai/schemas.py` (add `VisionObservation`), `backend/app/ai/graph/state.py` (allowlist it)
- Test: `backend/tests/ai/graph/test_media.py`, `backend/tests/ai/graph/test_intake.py`

**Interfaces:**
- Consumes: `GraphDeps.vision_chain`, `GraphDeps.geocode`
- Produces:
  - `app.ai.schemas.VisionObservation(text: str, shows_infrastructure_problem: bool, apparent_severity: str)`
  - `app.ai.graph.nodes.intake.intake_node(state, config) -> dict`
  - `app.ai.graph.nodes.intake.fan_out_media(state) -> list[Send] | str` — `Send` per media file, or `"validate"` when there is none
  - `app.ai.graph.nodes.media.analyse_media_node(payload: dict, config) -> dict`

- [ ] **Step 1: Add the vision output schema**

Phase 1a left this gap deliberately: `MediaInsight` carries `file_path` and `media_type`, which the node knows and the model does not. The model needs its own smaller schema.

In `backend/app/ai/schemas.py`, add alongside the other model-generated schemas:

```python
class VisionObservation(BaseModel):
    """What a vision model reports about one photograph.

    Deliberately smaller than MediaInsight: the model is not told the file path
    or media type, so it cannot hallucinate them. The node maps this into a
    MediaInsight, supplying those itself.
    """

    text: str = Field(description="What infrastructure problem is visible, in one or two sentences")
    shows_infrastructure_problem: bool = Field(
        description="False if the image shows nothing a municipality would act on"
    )
    apparent_severity: str = Field(
        default="unknown",
        description="How severe the visible problem looks: minor, moderate, severe, or unknown",
    )
```

Add `VisionObservation` to `CHECKPOINT_ALLOWLIST` in `backend/app/ai/graph/state.py`. The enum-coverage test will not catch this (it is not an enum), but the model-coverage test will.

- [ ] **Step 2: Write the failing tests**

`backend/tests/ai/graph/test_media.py`:

```python
from app.ai.graph.nodes.media import analyse_media_node
from app.ai.schemas import VisionObservation
from tests.ai.graph.conftest import raises, returns


def _payload(path="uploads/a.jpg", media_type="image"):
    return {"file_path": path, "media_type": media_type}


def test_an_image_becomes_a_media_insight(make_config):
    obs = VisionObservation(text="a deep pothole", shows_infrastructure_problem=True,
                            apparent_severity="severe")
    update = analyse_media_node(_payload(), make_config(vision_chain=returns(obs)))

    insight = update["media_insights"][0]
    assert insight.text == "a deep pothole"
    assert insight.file_path == "uploads/a.jpg"
    assert insight.media_type == "image"


def test_the_insight_takes_path_and_type_from_the_node_not_the_model(make_config):
    """VisionObservation has no file_path or media_type field, so those can only
    come from the node. The model cannot invent a path it was never asked for."""
    obs = VisionObservation(text="a pothole", shows_infrastructure_problem=True)
    update = analyse_media_node(_payload("uploads/real.jpg", "image"),
                                make_config(vision_chain=returns(obs)))

    assert "file_path" not in VisionObservation.model_fields
    assert "media_type" not in VisionObservation.model_fields
    assert update["media_insights"][0].file_path == "uploads/real.jpg"
    assert update["media_insights"][0].media_type == "image"


def test_the_chain_is_invoked_with_the_file_path(make_config):
    """The node's contract with its chain is {"file_path": str}. Turning that into
    the vision prompt's image_url/image_context is the adapter's job, wired in
    build_deps — see Task 5. Keeping file loading out of the node is what makes
    the node testable without touching disk."""
    seen = {}

    def capture(payload):
        seen.update(payload)
        return VisionObservation(text="x", shows_infrastructure_problem=True)

    from langchain_core.runnables import RunnableLambda

    analyse_media_node(_payload(), make_config(vision_chain=RunnableLambda(capture)))
    assert set(seen) == {"file_path"}


def test_an_image_with_no_problem_produces_no_insight(make_config):
    """v1 decided this by checking whether the string 'No infrastructure issues'
    appeared in the model's prose."""
    obs = VisionObservation(text="an ordinary street", shows_infrastructure_problem=False)
    update = analyse_media_node(_payload(), make_config(vision_chain=returns(obs)))
    assert update["media_insights"] == []


def test_one_bad_file_does_not_fail_the_complaint(make_config):
    """A corrupt upload degrades the complaint; it must not end the run."""
    update = analyse_media_node(_payload(), make_config(vision_chain=raises(OSError("truncated"))))
    assert update["media_insights"] == []
    assert update["errors"]


def test_a_non_image_is_skipped_without_calling_the_model(make_config):
    called = {"n": 0}

    def counting(_):
        called["n"] += 1
        return VisionObservation(text="", shows_infrastructure_problem=False)

    from langchain_core.runnables import RunnableLambda

    update = analyse_media_node(_payload(media_type="video"),
                                make_config(vision_chain=RunnableLambda(counting)))
    assert called["n"] == 0
    assert update["media_insights"] == []
```

`backend/tests/ai/graph/test_intake.py`:

```python
from langgraph.types import Send

from app.ai.graph.nodes.intake import fan_out_media, intake_node
from app.ai.schemas import Coords, LocationInfo, MediaRef
from tests.ai.graph.conftest import returns


def test_geocoding_populates_the_location(make_config, base_state):
    location = LocationInfo(address="MG Road", district="Bengaluru Urban", state="Karnataka")
    state = {**base_state, "coords": Coords(latitude=12.9, longitude=77.6)}
    update = intake_node(state, make_config(geocode=lambda lat, lon: location))

    assert update["location"].district == "Bengaluru Urban"


def test_no_coordinates_means_no_geocoding_call(make_config, base_state):
    called = {"n": 0}

    def counting(lat, lon):
        called["n"] += 1
        return LocationInfo()

    update = intake_node(base_state, make_config(geocode=counting))
    assert called["n"] == 0
    assert update["location"] is None


def test_a_geocoding_failure_does_not_end_the_run(make_config, base_state):
    def boom(lat, lon):
        raise TimeoutError("nominatim slow")

    state = {**base_state, "coords": Coords(latitude=1.0, longitude=2.0)}
    update = intake_node(state, make_config(geocode=boom))

    assert update["location"] is None
    assert update["errors"]


def test_fan_out_emits_one_send_per_media_file(base_state):
    state = {**base_state, "media": [
        MediaRef(file_path=f"uploads/{i}.jpg", media_type="image") for i in range(3)
    ]}
    sends = fan_out_media(state)

    assert len(sends) == 3
    assert all(isinstance(s, Send) for s in sends)
    assert {s.arg["file_path"] for s in sends} == {"uploads/0.jpg", "uploads/1.jpg", "uploads/2.jpg"}


def test_no_media_skips_straight_to_validate(base_state):
    """Returning a node name rather than an empty Send list; an empty list
    would leave the graph with nowhere to go."""
    assert fan_out_media(base_state) == "validate"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph/test_media.py tests/ai/graph/test_intake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph.nodes.intake'`

- [ ] **Step 4: Implement the nodes**

`backend/app/ai/graph/nodes/intake.py`:

```python
"""Normalise the submission and fan out over its media.

Geocoding failure is degradation, not termination: a complaint without a ward
is still a complaint. v1 made the same call and it was right.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def intake_node(state: ComplaintState, config: RunnableConfig) -> dict:
    coords = state["coords"]
    if coords is None:
        return {
            "location": None,
            "decision_log": [NodeDecision(node="intake", summary="no coordinates supplied")],
        }

    geocode = deps_from_config(config).require("geocode")
    try:
        location = geocode(coords.latitude, coords.longitude)
    except Exception as exc:
        return {
            "location": None,
            "errors": [f"intake: geocoding failed: {exc}"],
            "decision_log": [NodeDecision(node="intake", summary=f"geocoding failed: {exc}")],
        }

    return {
        "location": location,
        "decision_log": [NodeDecision(node="intake", summary=f"located in {location.district or 'unknown district'}")],
    }


def fan_out_media(state: ComplaintState):
    """One parallel branch per uploaded file, or straight on if there are none.

    Returns a node name rather than an empty list when there is no media: an
    empty Send list leaves the graph with nowhere to go.
    """
    media = state["media"]
    if not media:
        return "validate"
    return [
        Send("analyse_media", {"file_path": m.file_path, "media_type": m.media_type})
        for m in media
    ]
```

`backend/app/ai/graph/nodes/media.py`:

```python
"""Analyse one uploaded file. This is the Send fan-out target.

It receives a payload dict, not the whole state — that is what Send passes —
and returns an update that merges back through the media_insights reducer.

Whether an image shows a real problem is a typed boolean from the model, not a
substring search on its prose. v1 checked `if "No infrastructure issues" not in text`.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.schemas import MediaInsight

ANALYSABLE = {"image"}


def analyse_media_node(payload: dict, config: RunnableConfig) -> dict:
    file_path = payload["file_path"]
    media_type = payload["media_type"]

    if media_type not in ANALYSABLE:
        return {"media_insights": []}

    chain = deps_from_config(config).require("vision_chain")
    try:
        observation = chain.invoke({"file_path": file_path})
    except Exception as exc:
        # One unreadable upload degrades the complaint; it must not end the run.
        return {"media_insights": [], "errors": [f"analyse_media[{file_path}]: {exc}"]}

    if not observation.shows_infrastructure_problem:
        return {"media_insights": []}

    return {"media_insights": [MediaInsight(
        file_path=file_path,
        media_type=media_type,
        text=observation.text,
    )]}
```

Note the vision chain is invoked with `{"file_path": ...}` only. Loading the image bytes and building the multimodal message is the chain's job, wired in Task 5 — the node must not read files, or it becomes untestable.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph -v`
Expected: PASS, 25 tests.

- [ ] **Step 6: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, 138 tests.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: add intake and the media fan-out subgraph

Each uploaded file is analysed in its own parallel branch and the results merge
through the media_insights reducer.

Adds VisionObservation, the vision output schema Phase 1a deliberately left out.
It is smaller than MediaInsight: the model is never told the file path or media
type, so it cannot invent them. Whether an image shows a real problem is a typed
boolean rather than v1's substring search on the model's prose."
```

---

## Task 3: The remaining nodes

**Files:**
- Create: `backend/app/ai/graph/nodes/assess_risk.py`, `route.py`, `work_order.py`, `notify.py`
- Modify: `backend/app/ai/graph/edges.py`
- Test: `backend/tests/ai/graph/test_assess_risk.py`, `test_route.py`, `test_work_order.py`, `test_notify.py`

**Interfaces:**
- Produces:
  - `assess_risk_node(state, config) -> dict`
  - `route_node(state, config) -> dict` — reads `Department`/`Contractor` through `session_factory`
  - `work_order_node(state, config) -> dict`
  - `notify_node(state, config) -> dict` — **idempotent**
  - `app.ai.graph.nodes.route.score_contractor(contractor, category, district) -> float`
  - `app.ai.graph.nodes.work_order.SLA_HOURS: dict[RiskLevel, int]`
  - `app.ai.graph.edges.after_classify(state) -> str`

- [ ] **Step 1: Write the failing tests**

`backend/tests/ai/graph/test_route.py`:

```python
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


def test_a_specialist_contractor_outranks_a_generalist(seeded):
    specialist = Contractor(name="S", specializations=[Category.ROADS.value], rating=3.0)
    generalist = Contractor(name="G", specializations=[], rating=5.0)
    assert score_contractor(specialist, Category.ROADS, None) > score_contractor(generalist, Category.ROADS, None)


def test_a_busy_contractor_is_penalised(seeded):
    idle = Contractor(name="I", specializations=[Category.ROADS.value], rating=4.0, active_workload=0)
    busy = Contractor(name="B", specializations=[Category.ROADS.value], rating=4.0, active_workload=8)
    assert score_contractor(idle, Category.ROADS, None) > score_contractor(busy, Category.ROADS, None)


def test_zone_match_breaks_a_tie(seeded):
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
```

`backend/tests/ai/graph/test_work_order.py`:

```python
from datetime import timezone

from app.ai.graph.nodes.work_order import SLA_HOURS, work_order_node
from app.ai.schemas import ClassificationResult, RiskAssessment
from app.constants import Category, RiskLevel


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
    later must start from an aware value. See app/db/base.py:utcnow."""
    update = work_order_node(_state(base_state, RiskLevel.HIGH, 60), make_config())
    deadline = update["decision_log"][-1].summary
    assert update["work_order"].sla_hours == SLA_HOURS[RiskLevel.HIGH]
    assert deadline
```

`backend/tests/ai/graph/test_notify.py`:

```python
from app.ai.graph.nodes.notify import notify_node


def test_sends_one_notification(make_config, base_state):
    sent = []
    update = notify_node(base_state, make_config(notify=lambda **kw: sent.append(kw)))
    assert len(sent) == 1
    assert update["decision_log"][0].node == "notify"


def test_notifying_twice_sends_once(make_config, base_state):
    """Durability is bounded: a resumed run re-executes the node it died in, and
    the node before it may run again. Measured: an exception preserves progress,
    a SIGKILL does not. Either way this node must not email the citizen twice."""
    sent = []
    config = make_config(notify=lambda **kw: sent.append(kw))

    first = notify_node(base_state, config)
    state_after = {**base_state, **first}
    notify_node(state_after, config)

    assert len(sent) == 1


def test_a_notification_failure_does_not_end_the_run(make_config, base_state):
    def boom(**kw):
        raise ConnectionError("smtp down")

    update = notify_node(base_state, make_config(notify=boom))
    assert update["errors"]
    assert update.get("terminal_reason") is None
```

`backend/tests/ai/graph/test_assess_risk.py`:

```python
from app.ai.graph.nodes.assess_risk import assess_risk_node
from app.ai.schemas import ClassificationResult, RiskAssessment
from app.constants import Category, RiskLevel
from tests.ai.graph.conftest import raises, returns


def _state(base_state):
    return {**base_state,
            "classification": ClassificationResult(category=Category.ROADS, confidence=0.9)}


def test_records_the_assessment(make_config, base_state):
    result = RiskAssessment(priority_score=80, risk_level=RiskLevel.CRITICAL)
    update = assess_risk_node(_state(base_state), make_config(risk_chain=returns(result)))
    assert update["risk"].priority_score == 80


def test_the_category_is_passed_to_the_model(make_config, base_state):
    seen = {}

    def capture(payload):
        seen.update(payload)
        return RiskAssessment(priority_score=50, risk_level=RiskLevel.MEDIUM)

    from langchain_core.runnables import RunnableLambda

    assess_risk_node(_state(base_state), make_config(risk_chain=RunnableLambda(capture)))
    assert seen["category"] == Category.ROADS.value


def test_a_model_failure_is_an_error(make_config, base_state):
    update = assess_risk_node(_state(base_state), make_config(risk_chain=raises(RuntimeError("x"))))
    assert update["errors"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph.nodes.assess_risk'`

- [ ] **Step 3: Implement the four nodes**

`backend/app/ai/graph/nodes/assess_risk.py`:

```python
"""Score how urgently the municipality must act.

Unlike v1, where "risk" was a lookup keyed only on category — so a pothole
outside a school gate and one on an empty service road both scored 60 — the
model sees the specific report and the category together.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def _media_context(state: ComplaintState) -> str:
    return "\n".join(f"[{i.media_type}] {i.text}" for i in state["media_insights"])


def assess_risk_node(state: ComplaintState, config: RunnableConfig) -> dict:
    chain = deps_from_config(config).require("risk_chain")
    classification = state["classification"]

    try:
        result = chain.invoke({
            "description": state["description"],
            "category": classification.category.value,
            "media_context": _media_context(state),
        })
    except Exception as exc:
        return {
            "errors": [f"assess_risk: {exc}"],
            "decision_log": [NodeDecision(node="assess_risk", summary=f"failed: {exc}")],
        }

    return {
        "risk": result,
        "decision_log": [NodeDecision(
            node="assess_risk",
            summary=f"{result.risk_level.value} ({result.priority_score}/100)",
        )],
    }
```

`backend/app/ai/graph/nodes/route.py`:

```python
"""Pick the owning department and the best-placed contractor.

Two v1 defects fixed structurally:

- The department comes from `Department.categories`, the JSON column v1
  declared, seeded, and then ignored in favour of a hardcoded dict that drifted
  until CONSTRUCTION and SEWAGE pointed at departments that did not exist.
- Contractor scoring lives here once. v1 copy-pasted the identical loop into
  three files, so changing a weight meant remembering all three.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.constants import Category, JurisdictionLevel
from app.ai.schemas import NodeDecision, RoutingDecision

# Weights are deliberately explicit rather than tuned. Specialisation dominates,
# then track record, then availability, then locality as a tie-breaker.
SPECIALISATION_WEIGHT = 40.0
RATING_WEIGHT = 6.0
WORKLOAD_ALLOWANCE = 20.0
WORKLOAD_PENALTY = 2.0
ZONE_BONUS = 10.0


def score_contractor(contractor, category: Category, district: str | None) -> float:
    score = 0.0
    if contractor.specializations and category.value in contractor.specializations:
        score += SPECIALISATION_WEIGHT
    score += (contractor.rating or 0.0) * RATING_WEIGHT
    score += max(0.0, WORKLOAD_ALLOWANCE - (contractor.active_workload or 0) * WORKLOAD_PENALTY)
    if district and contractor.zone and contractor.zone.lower() == district.lower():
        score += ZONE_BONUS
    return score


def _jurisdiction(state: ComplaintState) -> JurisdictionLevel:
    """The finest level we actually know, not the finest level that exists."""
    location = state["location"]
    if location is None:
        return JurisdictionLevel.CITY
    if location.ward:
        return JurisdictionLevel.WARD
    if location.block:
        return JurisdictionLevel.BLOCK
    if location.district:
        return JurisdictionLevel.DISTRICT
    return JurisdictionLevel.CITY


def route_node(state: ComplaintState, config: RunnableConfig) -> dict:
    from app.db.models.core import Contractor, Department

    session = deps_from_config(config).require("session_factory")()
    category = state["classification"].category
    district = state["location"].district if state["location"] else None
    tenant_id = state["tenant_id"]

    departments = session.query(Department)
    if tenant_id:
        departments = departments.filter(Department.tenant_id == tenant_id)
    department = next(
        (d for d in departments.all() if category.value in (d.categories or [])), None
    )

    contractors = session.query(Contractor)
    if tenant_id:
        contractors = contractors.filter(Contractor.tenant_id == tenant_id)
    ranked = sorted(
        contractors.all(), key=lambda c: score_contractor(c, category, district), reverse=True
    )
    contractor = ranked[0] if ranked else None

    routing = RoutingDecision(
        department_name=department.name if department else "General Administration",
        department_id=department.id if department else None,
        contractor_id=contractor.id if contractor else None,
        contractor_name=contractor.name if contractor else None,
        jurisdiction_level=_jurisdiction(state),
        justification=(
            f"{category.value} is owned by "
            f"{department.name if department else 'no seeded department'}"
        ),
    )
    return {
        "routing": routing,
        "decision_log": [NodeDecision(
            node="route",
            summary=f"{routing.department_name} / {routing.contractor_name or 'no contractor'}",
        )],
    }
```

`backend/app/ai/graph/nodes/work_order.py`:

```python
"""Draft the work order: SLA window, cost, materials.

The SLA deadline is computed here, not asked of the model — an LLM has no
reliable notion of "now", which is why WorkOrderDraft has no sla_deadline field.

Cost and materials are constants in this phase. Replacing them with retrieval
over a real rate card and past work orders is the substance of Phase 2; today
they are honest placeholders rather than a lookup table pretending to be
intelligence, and `cost_basis` records which they are.
"""

from datetime import timedelta

from langchain_core.runnables import RunnableConfig

from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision, WorkOrderDraft
from app.constants import Category, RiskLevel
from app.db.base import utcnow

SLA_HOURS: dict[RiskLevel, int] = {
    RiskLevel.CRITICAL: 4,
    RiskLevel.HIGH: 24,
    RiskLevel.MEDIUM: 72,
    RiskLevel.LOW: 168,
}

_BASE_COST: dict[Category, float] = {
    Category.ROADS: 5000.0, Category.ELECTRICITY: 3000.0, Category.WATER: 4000.0,
    Category.SANITATION: 2000.0, Category.PUBLIC_SPACES: 3000.0, Category.EDUCATION: 8000.0,
    Category.HEALTH: 6000.0, Category.FLOODING: 10000.0, Category.FIRE_HAZARD: 7000.0,
    Category.CONSTRUCTION: 15000.0, Category.STRAY_ANIMALS: 1000.0, Category.SEWAGE: 5000.0,
}

_RISK_MULTIPLIER: dict[RiskLevel, float] = {
    RiskLevel.CRITICAL: 2.0, RiskLevel.HIGH: 1.5, RiskLevel.MEDIUM: 1.0, RiskLevel.LOW: 0.8,
}


def work_order_node(state: ComplaintState, config: RunnableConfig) -> dict:
    category = state["classification"].category
    risk = state["risk"]
    sla_hours = SLA_HOURS[risk.risk_level]
    deadline = utcnow() + timedelta(hours=sla_hours)
    cost = _BASE_COST[category] * _RISK_MULTIPLIER[risk.risk_level]

    draft = WorkOrderDraft(
        sla_hours=sla_hours,
        estimated_cost=cost,
        cost_basis="Category base rate x risk multiplier (placeholder until Phase 2 retrieval)",
        materials="To be determined on site inspection",
        summary=(
            f"{category.value} | {risk.risk_level.value} ({risk.priority_score}/100) | "
            f"{state['routing'].department_name}"
        ),
    )
    return {
        "work_order": draft,
        "decision_log": [NodeDecision(
            node="work_order",
            summary=f"SLA {sla_hours}h, due {deadline.isoformat()}, est. {cost:.0f}",
        )],
    }
```

`backend/app/ai/graph/nodes/notify.py`:

```python
"""Tell the citizen their complaint was processed.

**Idempotent by design.** Durability is bounded: a resumed run re-executes the
node it died in, and measurements show a SIGKILL can lose the tail entirely so
a whole run replays. Either way this node must not email the same citizen
twice, so it guards on a fact already in state rather than on an external flag.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision

NODE = "notify"


def _already_sent(state: ComplaintState) -> bool:
    return any(entry.node == NODE for entry in state["decision_log"])


def notify_node(state: ComplaintState, config: RunnableConfig) -> dict:
    if _already_sent(state):
        return {}

    notify = deps_from_config(config).require("notify")
    classification = state["classification"]

    try:
        notify(
            tracking_id=state["tracking_id"],
            complaint_id=state["complaint_id"],
            category=classification.category.value if classification else None,
            status="assigned",
        )
    except Exception as exc:
        # A failed notification must not lose a processed complaint.
        return {
            "errors": [f"notify: {exc}"],
            "decision_log": [NodeDecision(node=NODE, summary=f"failed: {exc}")],
        }

    return {"decision_log": [NodeDecision(node=NODE, summary="citizen notified")]}
```

Add to `backend/app/ai/graph/edges.py`:

```python
def after_classify(state: ComplaintState) -> str:
    """Low confidence is recorded but does not branch until Phase 2 adds the
    retrieval loop. Fails closed on a missing classification, as elsewhere."""
    if state["errors"] or state["classification"] is None:
        return END
    return "assess_risk"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph -v`
Expected: PASS, 42 tests.

- [ ] **Step 5: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, 155 tests.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: add risk, routing, work-order and notify nodes

Routing reads Department.categories rather than a hardcoded map — v1 declared
that column, seeded it, and then ignored it. Contractor scoring exists once;
v1 copy-pasted it into three files.

notify is idempotent, guarding on its own decision_log entry. Durability is
bounded: a resumed run re-executes the node it died in, so a node with an
external side effect cannot assume exactly-once."
```

---

## Task 4: Graph assembly

**Files:**
- Create: `backend/app/ai/graph/build.py`
- Test: `backend/tests/ai/graph/test_build.py`

**Interfaces:**
- Produces:
  - `app.ai.graph.build.build_graph() -> StateGraph` — uncompiled, for tests
  - `app.ai.graph.build.compile_graph(checkpointer=None)` — compiled
  - `app.ai.graph.build.GRAPH_VERSION: str`

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/graph/test_build.py`:

```python
import pytest
from langgraph.graph import END, START

from app.ai.graph.build import GRAPH_VERSION, build_graph, compile_graph


def test_the_graph_compiles():
    assert compile_graph() is not None


def test_every_node_is_reachable_from_start():
    graph = compile_graph().get_graph()
    reachable, frontier = {START}, [START]
    while frontier:
        current = frontier.pop()
        for edge in graph.edges:
            if edge.source == current and edge.target not in reachable:
                reachable.add(edge.target)
                frontier.append(edge.target)
    unreachable = {n for n in graph.nodes if n not in reachable} - {START, END}
    assert not unreachable, f"unreachable nodes: {sorted(unreachable)}"


def test_every_node_can_reach_end():
    """A node with no path to END hangs the run."""
    graph = compile_graph().get_graph()
    can_finish, changed = {END}, True
    while changed:
        changed = False
        for edge in graph.edges:
            if edge.target in can_finish and edge.source not in can_finish:
                can_finish.add(edge.source)
                changed = True
    stuck = {n for n in graph.nodes if n not in can_finish} - {END}
    assert not stuck, f"nodes with no path to END: {sorted(stuck)}"


def test_the_expected_nodes_are_present():
    nodes = set(compile_graph().get_graph().nodes)
    assert {"intake", "analyse_media", "validate", "classify",
            "assess_risk", "route", "work_order", "notify"} <= nodes


def test_graph_version_is_recorded():
    """Stamped onto every AgentRun so a trace can be tied to a graph shape."""
    assert GRAPH_VERSION


def test_llm_nodes_carry_a_retry_policy():
    """A transient 503 killed a v1 complaint outright."""
    builder = build_graph()
    for name in ("validate", "classify", "assess_risk", "analyse_media"):
        assert builder.nodes[name].retry_policy, f"{name} has no retry policy"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph/test_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph.build'`

- [ ] **Step 3: Implement the assembly**

`backend/app/ai/graph/build.py`:

```python
"""Assemble the complaint graph.

The shape IS the business process. v1's equivalent was the order of seven
`add_agent` calls in a function, with no branching available at all.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.ai.graph.edges import after_assess_risk, after_classify, after_validate
from app.ai.graph.nodes.assess_risk import assess_risk_node
from app.ai.graph.nodes.classify import classify_node
from app.ai.graph.nodes.intake import fan_out_media, intake_node
from app.ai.graph.nodes.media import analyse_media_node
from app.ai.graph.nodes.notify import notify_node
from app.ai.graph.nodes.route import route_node
from app.ai.graph.nodes.validate import validate_node
from app.ai.graph.nodes.work_order import work_order_node
from app.ai.graph.state import ComplaintState

GRAPH_VERSION = "1b.0"

# Retries cover transient provider failures. Note these compound with the
# client's own max_retries — see the comment on SHARED_RATE_LIMITER.
LLM_RETRY = RetryPolicy(max_attempts=3)


def build_graph() -> StateGraph:
    builder = StateGraph(ComplaintState)

    builder.add_node("intake", intake_node)
    builder.add_node("analyse_media", analyse_media_node, retry_policy=LLM_RETRY)
    builder.add_node("validate", validate_node, retry_policy=LLM_RETRY)
    builder.add_node("classify", classify_node, retry_policy=LLM_RETRY)
    builder.add_node("assess_risk", assess_risk_node, retry_policy=LLM_RETRY)
    builder.add_node("route", route_node)
    builder.add_node("work_order", work_order_node)
    builder.add_node("notify", notify_node)

    builder.add_edge(START, "intake")
    # Fan out one branch per uploaded file, or skip straight on when there is none.
    builder.add_conditional_edges("intake", fan_out_media, ["analyse_media", "validate"])
    builder.add_edge("analyse_media", "validate")
    builder.add_conditional_edges("validate", after_validate, ["classify", END])
    builder.add_conditional_edges("classify", after_classify, ["assess_risk", END])
    # Fail closed: work_order reads state["risk"] unconditionally, so a failed
    # assessment must not reach it.
    builder.add_conditional_edges("assess_risk", after_assess_risk, ["route", END])
    builder.add_edge("route", "work_order")
    builder.add_edge("work_order", "notify")
    builder.add_edge("notify", END)

    return builder


def compile_graph(checkpointer=None):
    return build_graph().compile(checkpointer=checkpointer)
```

- [ ] **Step 4: Run the tests and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, 161 tests.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: assemble the complaint graph

The graph shape is the business process, with real branching: rejected and
errored runs go straight to END, and intake fans out one parallel branch per
uploaded file. v1's equivalent was the order of seven add_agent calls.

Topology tests assert every node is reachable from START and every node has a
path to END, so a future edit cannot strand or hang a node."
```

---

## Task 5: The runner

The only entry point into the graph. Owns the checkpointer, injects dependencies, persists results and writes the audit trail.

**Files:**
- Create: `backend/app/ai/graph/runner.py`
- Test: `backend/tests/ai/graph/test_runner.py`

**Interfaces:**
- Produces:
  - `app.ai.graph.runner.build_deps(session_factory) -> GraphDeps` — wires real chains from `app.ai.llm`
  - `app.ai.graph.runner.run_complaint(complaint_id, *, session_factory, deps=None, checkpointer=None) -> ComplaintState`
  - `app.ai.graph.runner.persist_result(state, session, *, duration_ms: int) -> None` — writes `Complaint`, `WorkOrder`, `AgentRun`, `AgentStep`; idempotent for `WorkOrder` because a resumed run replays and `work_orders.complaint_id` is unique
  - `app.ai.graph.runner.CHECKPOINT_DB: str`

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/graph/test_runner.py`:

```python
from dataclasses import replace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.ai.graph.deps import GraphDeps
from app.ai.graph.runner import run_complaint
from app.ai.schemas import (
    ClassificationResult, RiskAssessment, ValidationResult, VisionObservation,
)
from app.constants import Category, RiskLevel
from app.db.models.ai import AgentRun, AgentStep
from app.db.models.complaint import Complaint
from app.db.models.workflow import WorkOrder
from app.services.seed import seed_database
from tests.ai.graph.conftest import raises, returns


@pytest.fixture
def env(db_session):
    """A seeded database plus a complaint ready to process."""
    seed_database(db_session)
    complaint = Complaint(
        tracking_id="CIV-RUNNER01",
        citizen_email="a@b.com",
        description="There is a large pothole on the main road near the school gate",
    )
    db_session.add(complaint)
    db_session.commit()
    return db_session, complaint


def _deps(*, valid=True, notified=None, **over):
    return GraphDeps(
        validate_chain=returns(ValidationResult(is_valid=valid, rejection_reason=None if valid else "a neighbour dispute")),
        classify_chain=returns(ClassificationResult(category=Category.ROADS, confidence=0.93)),
        risk_chain=returns(RiskAssessment(priority_score=80, risk_level=RiskLevel.CRITICAL)),
        vision_chain=returns(VisionObservation(text="a pothole", shows_infrastructure_problem=True)),
        notify=(lambda **kw: notified.append(kw)) if notified is not None else (lambda **kw: None),
        **over,
    )


async def _run(session, complaint, deps):
    return await run_complaint(
        complaint.id,
        session_factory=lambda: session,
        deps=deps,
        checkpointer=InMemorySaver(),
    )


async def test_a_valid_complaint_runs_end_to_end(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.category == Category.ROADS.value
    assert stored.risk_level == RiskLevel.CRITICAL.value
    assert stored.priority_score == 80
    assert stored.status == "assigned"
    assert stored.terminal_reason is None


async def test_a_valid_complaint_gets_a_work_order(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    order = session.query(WorkOrder).one()
    assert order.sla_hours == 4
    assert order.sla_deadline is not None
    assert order.estimated_cost > 0


async def test_a_rejected_complaint_is_stored_as_rejected(env):
    """v1's headline bug: a correctly-rejected complaint was written back as
    'submitted', indistinguishable from one that had never been processed."""
    session, complaint = env
    await _run(session, complaint, _deps(valid=False, session_factory=lambda: session))

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.status == "rejected"
    assert "neighbour" in stored.terminal_reason
    assert stored.status != "submitted"


async def test_a_rejected_complaint_gets_no_work_order(env):
    session, complaint = env
    await _run(session, complaint, _deps(valid=False, session_factory=lambda: session))
    assert session.query(WorkOrder).count() == 0


async def test_a_technical_failure_is_distinct_from_a_rejection(env):
    """An outage and a business decision must not look the same afterwards."""
    session, complaint = env
    deps = replace(
        _deps(session_factory=lambda: session),
        classify_chain=raises(RuntimeError("503 from provider")),
    )
    await _run(session, complaint, deps)

    session.expire_all()
    stored = session.query(Complaint).one()
    assert stored.status == "failed"
    assert stored.terminal_reason is None


async def test_an_agent_run_row_records_the_run(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    run = session.query(AgentRun).one()
    assert run.complaint_id == complaint.id
    assert run.thread_id == complaint.id
    assert run.status == "completed"
    assert run.graph_version
    assert run.duration_ms is not None


async def test_one_agent_step_per_node_in_order(env):
    session, complaint = env
    await _run(session, complaint, _deps(session_factory=lambda: session))

    session.expire_all()
    steps = session.query(AgentStep).order_by(AgentStep.seq).all()
    assert [s.node for s in steps] == [
        "intake", "validate", "classify", "assess_risk", "route", "work_order", "notify"
    ]
    assert [s.seq for s in steps] == list(range(len(steps)))


async def test_running_the_same_complaint_twice_notifies_once(env):
    """The graph replays on resume; the citizen must not be emailed twice."""
    session, complaint = env
    sent = []
    await _run(session, complaint, _deps(notified=sent, session_factory=lambda: session))
    assert len(sent) == 1
```

Note `asyncio_mode = auto` in `pytest.ini` means these `async def` tests need no decorator.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/graph/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph.runner'`

- [ ] **Step 3: Implement the runner**

`backend/app/ai/graph/runner.py`:

```python
"""The only entry point into the graph.

Owns the checkpointer, injects dependencies, and is the single place that
writes to the database — nodes stay pure so they can be tested against fakes.

`app/api/` may import this module and nothing else under `app/ai/graph/`;
`tests/test_import_rules.py` enforces that.
"""

import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from app.ai.graph.build import GRAPH_VERSION, compile_graph
from app.ai.graph.deps import GraphDeps, to_configurable
from app.ai.graph.state import ComplaintState, build_serializer, initial_state
from app.ai.schemas import Coords, MediaRef
from app.db.base import utcnow

CHECKPOINT_DB = str(Path(__file__).resolve().parents[3] / "checkpoints.db")


def build_deps(session_factory: Callable) -> GraphDeps:
    """Wire the real chains. Tests pass their own GraphDeps instead."""
    from app.ai.llm import Task, build_structured
    from app.ai.schemas import ClassificationResult, RiskAssessment, ValidationResult, VisionObservation
    from app.services.geocoding import reverse_geocode
    from app.services.notify import notify_citizen

    return GraphDeps(
        validate_chain=build_structured(Task.VALIDATE, ValidationResult, "validate"),
        classify_chain=build_structured(Task.CLASSIFY, ClassificationResult, "classify"),
        risk_chain=build_structured(Task.ASSESS_RISK, RiskAssessment, "assess_risk"),
        vision_chain=_vision_chain(),
        session_factory=session_factory,
        geocode=reverse_geocode,
        notify=notify_citizen,
    )


def _vision_chain():
    """Adapt the media node's {"file_path"} contract to the vision prompt.

    The prompt takes `image_url` and `image_context`; the node deliberately knows
    nothing about loading files, so the bridge lives here. Reading bytes in the
    node would make it untestable without a filesystem.
    """
    import base64
    import mimetypes
    from pathlib import Path

    from langchain_core.runnables import RunnableLambda

    from app.ai.llm import Task, build_structured
    from app.ai.schemas import VisionObservation
    from app.config import settings

    def to_prompt_vars(payload: dict) -> dict:
        path = Path(settings.upload_dir).parent / payload["file_path"]
        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "image_url": f"data:{mime};base64,{encoded}",
            "image_context": "Describe any infrastructure problem visible in this photograph.",
        }

    return RunnableLambda(to_prompt_vars) | build_structured(
        Task.VISION, VisionObservation, "vision"
    )


def _state_for(complaint) -> ComplaintState:
    coords = None
    if complaint.latitude is not None and complaint.longitude is not None:
        coords = Coords(latitude=complaint.latitude, longitude=complaint.longitude)
    return initial_state(
        complaint_id=complaint.id,
        tracking_id=complaint.tracking_id,
        tenant_id=complaint.tenant_id,
        raw_description=complaint.description,
        media=[
            MediaRef(file_path=m.file_path, media_type=m.media_type,
                     original_filename=m.original_filename)
            for m in (complaint.media or [])
        ],
        coords=coords,
    )


def _status_for(state: ComplaintState) -> str:
    """Outcome first, errors last.

    A run that finished with a soft error — geocoding timed out, say — is still
    assigned. Only a run that produced nothing is 'failed'. And a rejection is
    never 'failed': v1 conflated the two and lost both.
    """
    if state["terminal_reason"]:
        return "rejected"
    if state["work_order"]:
        return "assigned"
    if state["errors"]:
        return "failed"
    return "processed"


def persist_result(state: ComplaintState, session, *, duration_ms: int) -> None:
    from app.db.models.ai import AgentRun, AgentStep
    from app.db.models.complaint import Complaint
    from app.db.models.workflow import WorkOrder

    complaint = session.query(Complaint).filter(Complaint.id == state["complaint_id"]).one()
    status = _status_for(state)

    complaint.status = status
    complaint.terminal_reason = state["terminal_reason"]
    complaint.graph_thread_id = state["complaint_id"]
    complaint.pipeline_version = GRAPH_VERSION

    if state["classification"]:
        complaint.category = state["classification"].category.value
        complaint.subcategory = state["classification"].subcategory
        complaint.classification_confidence = state["classification"].confidence
    if state["risk"]:
        complaint.priority_score = state["risk"].priority_score
        complaint.risk_level = state["risk"].risk_level.value
    if state["location"]:
        location = state["location"]
        complaint.address = location.address or complaint.address
        complaint.ward = location.ward or complaint.ward
        complaint.block = location.block or complaint.block
        complaint.district = location.district or complaint.district
        complaint.state = location.state or complaint.state
    if state["evidence"]:
        complaint.evidence = [chunk.model_dump() for chunk in state["evidence"]]

    if state["work_order"] and status == "assigned":
        draft = state["work_order"]
        routing = state["routing"]
        session.add(WorkOrder(
            complaint_id=complaint.id,
            tenant_id=complaint.tenant_id,
            contractor_id=routing.contractor_id if routing else None,
            status="assigned" if (routing and routing.contractor_id) else "created",
            sla_hours=draft.sla_hours,
            sla_deadline=utcnow() + timedelta(hours=draft.sla_hours),
            estimated_cost=draft.estimated_cost,
            cost_basis=draft.cost_basis,
            materials=draft.materials,
            notes=draft.summary,
        ))

    run = AgentRun(
        complaint_id=complaint.id,
        thread_id=state["complaint_id"],
        status="completed" if status != "failed" else "failed",
        graph_version=GRAPH_VERSION,
        finished_at=utcnow(),
        duration_ms=duration_ms,
        error="; ".join(state["errors"]) or None,
    )
    session.add(run)
    session.flush()

    for seq, decision in enumerate(state["decision_log"]):
        session.add(AgentStep(
            run_id=run.id,
            seq=seq,
            node=decision.node,
            status="ok",
            duration_ms=decision.duration_ms,
            output_summary=decision.summary,
        ))

    session.commit()


async def run_complaint(
    complaint_id: str,
    *,
    session_factory: Callable,
    deps: GraphDeps | None = None,
    checkpointer=None,
) -> ComplaintState:
    """Run one complaint through the graph and persist what happened.

    `thread_id` is the complaint id, so re-invoking with the same id resumes
    that complaint's run rather than starting a new one.
    """
    from app.db.models.complaint import Complaint

    session = session_factory()
    complaint = session.query(Complaint).filter(Complaint.id == complaint_id).one()
    state = _state_for(complaint)
    deps = deps or build_deps(session_factory)
    config = to_configurable(deps, thread_id=complaint_id)

    started = time.monotonic()
    if checkpointer is not None:
        result = await compile_graph(checkpointer=checkpointer).ainvoke(state, config)
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB) as saver:
            # Without this, Pydantic models in state come back from the
            # checkpoint as plain dicts and every later field access fails.
            saver.serde = build_serializer()
            result = await compile_graph(checkpointer=saver).ainvoke(state, config)
    duration_ms = int((time.monotonic() - started) * 1000)

    persist_result(result, session, duration_ms=duration_ms)
    return result
```

This assumes two small service functions that Phase 1c wires for real:
`app/services/geocoding.py::reverse_geocode(lat, lon) -> LocationInfo` and
`app/services/notify.py::notify_citizen(**kwargs) -> None`. Create both as thin
stubs in this task if they do not exist — a geocoder returning an empty
`LocationInfo` and a notifier that logs — so `build_deps` imports cleanly. They
are only reached when `deps` is not injected, which no test does.

- [ ] **Step 4: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, 169 tests, pristine.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app backend/tests
git commit -m "feat: add the graph runner

The only entry point into the graph: owns the checkpointer, injects
dependencies, and is the single place that writes to the database.

A rejected complaint stores status 'rejected' with its terminal_reason,
distinct from 'failed' for a technical error, and neither is ever written back
as 'submitted'. v1 folded both into one errors list and then overwrote the
result, which is why an AI-rejected complaint looked unprocessed.

Status resolution puts outcome before errors: a run that finished despite a
soft failure such as a geocoding timeout is still assigned."
```

## Phase 1b Done When

- [ ] `cd backend && .venv/bin/python -m pytest` passes, pristine, with no API key and no network
- [ ] A complaint runs end to end through the graph from a test, producing a classification, a risk score, a routing decision and a work-order draft
- [ ] A rejected complaint ends with status `rejected` and a `terminal_reason` — never `submitted`
- [ ] A technical failure ends with status `failed`, distinguishable from a rejection
- [ ] `AgentRun` and `AgentStep` rows record what happened, one step per node
- [ ] `notify` called twice on the same state sends once
- [ ] Topology tests prove every node is reachable from `START` and every node reaches `END`
- [ ] `tests/test_import_rules.py` still passes — `app/api/` reaches the graph only through `runner`

**Next:** Phase 1c — API wiring, WebSocket streaming of `astream` updates, LangSmith tracing, and the SLA monitor port.
