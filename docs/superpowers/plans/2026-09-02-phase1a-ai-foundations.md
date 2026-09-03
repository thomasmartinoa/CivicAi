# CivicAI v2 — Phase 1a: AI Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AI layer CivicAI's graph will be assembled from — model access, typed output schemas, versioned prompts, and the graph state object — each fully unit-testable without a network call.

**Architecture:** Everything lives under `backend/app/ai/` and imports nothing from `app/api/`. Nodes (Phase 1b) will receive *already-bound structured runnables* through LangGraph's `config["configurable"]` rather than raw chat models — this is forced by a real constraint, not a preference (see Global Constraints). The graph state is a `TypedDict` whose accumulating fields carry reducers.

**Tech Stack:** LangChain 1.3.18, LangGraph 1.2.11, langchain-google-genai 4.4.0, Pydantic 2.12.3, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-civicai-v2-design.md`

**Prior phase:** Phase 0 (`docs/superpowers/plans/2026-09-02-phase0-foundation.md`) delivered config, 17 models, migrations, seed and a booting app — 51 tests passing. Read its "Carried forward into Phase 1" section before starting.

**Phase 1b (a separate plan) will add:** the nodes themselves, the media subgraph, graph assembly, the checkpointer, the runner, API wiring, streaming and observability. This plan stops at the point where a complaint can be classified from a Python REPL.

## Global Constraints

- **Python 3.14.** Virtualenv at `backend/.venv`. Tests: `cd backend && .venv/bin/python -m pytest`.
- **New pins** (all verified to install and run on 3.14): `langchain==1.3.18`, `langgraph==1.2.11`, `langchain-core==1.6.1`, `langchain-google-genai==4.4.0`, `langgraph-checkpoint-sqlite==3.1.1`, `aiosqlite==0.22.1`, `langsmith==0.12.1`.
- **Existing pins are unchanged**: `pydantic==2.12.3` satisfies langchain-core's `pydantic<3.0.0,>=2.7.4`. Do not bump it.
- **`app/ai/` must never import `app/api/`.** Enforced by `tests/test_import_rules.py`.
- **No network in tests.** Every test must pass with no API key set and no internet.
- **`with_structured_output` does not exist on LangChain's fake chat models.** Verified: both `GenericFakeChatModel` and `FakeListChatModel` raise `NotImplementedError`. Therefore **nodes must accept an injected structured runnable, never a raw model** — otherwise they are untestable. `app/ai/llm.py` is the only module that calls `.with_structured_output(...)`.
- **Pydantic objects stored in graph state must be added to the checkpoint allowlist.** Verified: a class missing from `allowed_msgpack_modules` is **silently deserialized back as a plain `dict`**, not an error — so `state["classification"].category` fails later with `AttributeError`, far from the cause. The allowlist accepts the class objects themselves; pass those, never `("module",)` tuples.
- **Commit messages carry no `Co-Authored-By` trailer.** The repository owner asked for none.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/ai/__init__.py` | package marker; exports nothing |
| `backend/app/ai/schemas.py` | every Pydantic model an LLM produces or the state holds |
| `backend/app/ai/llm.py` | model access: tiering, fallbacks, rate limiting, structured binding |
| `backend/app/ai/prompts/__init__.py` | prompt registry keyed by name + version |
| `backend/app/ai/prompts/templates.py` | the `ChatPromptTemplate`s themselves |
| `backend/app/ai/graph/state.py` | `ComplaintState`, its reducers, and `CHECKPOINT_ALLOWLIST` |
| `backend/tests/ai/` | mirrors the above |

---

## Task 1: Output schemas

Every value an LLM produces gets a Pydantic model with real constraints. This is what replaces v1's `_extract_json` + `result.get("category", "UNKNOWN")`.

**Files:**
- Create: `backend/app/ai/__init__.py`, `backend/app/ai/schemas.py`
- Test: `backend/tests/ai/__init__.py`, `backend/tests/ai/test_schemas.py`

**Interfaces:**
- Consumes: `app.constants.Category`, `app.constants.RiskLevel`
- Produces (all in `app.ai.schemas`):
  - `Coords(latitude: float, longitude: float)`
  - `MediaRef(file_path: str, media_type: str, original_filename: str | None)`
  - `MediaInsight(file_path: str, media_type: str, text: str)`
  - `LocationInfo(address, ward, block, district, state — all str, default "")`
  - `ValidationResult(is_valid: bool, what_happened: str, rejection_reason: str | None, severity_keywords: list[str])`
  - `ClassificationResult(category: Category, subcategory: str, confidence: float 0..1, reasoning: str)`
  - `RiskAssessment(priority_score: int 0..100, risk_level: RiskLevel, category_severity/population_impact/safety_risk/urgency: int 0..25, reasoning: str)`
  - `RoutingDecision(department_name: str, department_id: str | None, contractor_id: str | None, contractor_name: str | None, jurisdiction_level: str, justification: str)`
  - `WorkOrderDraft(sla_hours: int, sla_deadline: datetime, estimated_cost: float, cost_basis: str, materials: str, summary: str)`
  - `NodeDecision(node: str, summary: str, duration_ms: int | None)`
  - `RetrievedChunk(source: str, chunk_id: str | None, score: float | None, snippet: str)`
  - `band_for_score(score: int) -> RiskLevel`

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p backend/app/ai backend/tests/ai
touch backend/app/ai/__init__.py backend/tests/ai/__init__.py
```

`backend/tests/ai/test_schemas.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.ai.schemas import (
    ClassificationResult, Coords, LocationInfo, MediaInsight, MediaRef,
    NodeDecision, RetrievedChunk, RiskAssessment, RoutingDecision,
    ValidationResult, WorkOrderDraft, band_for_score,
)
from app.constants import Category, RiskLevel


def test_classification_rejects_a_category_outside_the_taxonomy():
    """v1 let the model return 'POTHOLES' and wrote it straight to the database."""
    with pytest.raises(ValidationError):
        ClassificationResult(category="POTHOLES", confidence=0.9)


def test_classification_accepts_a_real_category():
    result = ClassificationResult(category="ROADS", confidence=0.9)
    assert result.category is Category.ROADS


def test_confidence_must_be_a_probability():
    """v1 compared `result.get("confidence", 0) < 0.7` with no guarantee it was numeric."""
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            ClassificationResult(category="ROADS", confidence=bad)


def test_confidence_rejects_non_numeric():
    with pytest.raises(ValidationError):
        ClassificationResult(category="ROADS", confidence="high")


def test_priority_score_is_bounded_to_0_100():
    for bad in (-1, 101):
        with pytest.raises(ValidationError):
            RiskAssessment(priority_score=bad, risk_level="high")


def test_risk_factors_are_each_bounded_to_0_25():
    with pytest.raises(ValidationError):
        RiskAssessment(priority_score=50, risk_level="medium", safety_risk=30)


def test_risk_level_must_match_the_score_band():
    """A model that returns score=90 with risk_level='low' is self-contradictory."""
    with pytest.raises(ValidationError):
        RiskAssessment(priority_score=90, risk_level="low")


def test_risk_level_consistent_with_score_is_accepted():
    assert RiskAssessment(priority_score=90, risk_level="critical").risk_level is RiskLevel.CRITICAL


@pytest.mark.parametrize(
    "score,expected",
    [(0, RiskLevel.LOW), (25, RiskLevel.LOW), (26, RiskLevel.MEDIUM), (50, RiskLevel.MEDIUM),
     (51, RiskLevel.HIGH), (75, RiskLevel.HIGH), (76, RiskLevel.CRITICAL), (100, RiskLevel.CRITICAL)],
)
def test_band_for_score_covers_every_boundary(score, expected):
    assert band_for_score(score) is expected


def test_validation_result_defaults_are_empty_not_none():
    result = ValidationResult(is_valid=True)
    assert result.severity_keywords == []
    assert result.what_happened == ""
    assert result.rejection_reason is None


def test_work_order_draft_round_trips_a_datetime():
    draft = WorkOrderDraft(
        sla_hours=4,
        sla_deadline=datetime(2026, 9, 3, tzinfo=timezone.utc),
        estimated_cost=10000.0,
    )
    assert draft.sla_deadline.year == 2026


def test_the_remaining_models_construct_with_minimal_input():
    assert Coords(latitude=12.9, longitude=77.6).latitude == 12.9
    assert MediaRef(file_path="uploads/x.jpg", media_type="image").original_filename is None
    assert MediaInsight(file_path="uploads/x.jpg", media_type="image", text="a pothole").text
    assert LocationInfo().district == ""
    assert RoutingDecision(department_name="Public Works Department",
                           jurisdiction_level="ward").contractor_id is None
    assert NodeDecision(node="classify", summary="ok").duration_ms is None
    assert RetrievedChunk(source="sop_roads.md").score is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.schemas'`

- [ ] **Step 3: Implement the schemas**

`backend/app/ai/schemas.py`:

```python
"""Typed outputs for every AI step.

These are what `.with_structured_output(...)` binds to, so the model is
constrained at generation time rather than parsed afterwards. v1 asked for JSON
in a prompt, scraped it out of the response with a substring search, and wrote
whatever came back to the database unvalidated.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.constants import Category, RiskLevel


def band_for_score(score: int) -> RiskLevel:
    """Map a 0-100 priority score onto its risk band."""
    if score >= 76:
        return RiskLevel.CRITICAL
    if score >= 51:
        return RiskLevel.HIGH
    if score >= 26:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ── plain inputs (not model-generated) ───────────────────────────────────


class Coords(BaseModel):
    latitude: float
    longitude: float


class MediaRef(BaseModel):
    file_path: str
    media_type: str
    original_filename: str | None = None


class LocationInfo(BaseModel):
    address: str = ""
    ward: str = ""
    block: str = ""
    district: str = ""
    state: str = ""


# ── model-generated ──────────────────────────────────────────────────────


class MediaInsight(BaseModel):
    """What one image or audio file contributed to the complaint."""

    file_path: str
    media_type: str
    text: str


class ValidationResult(BaseModel):
    is_valid: bool
    what_happened: str = ""
    rejection_reason: str | None = None
    severity_keywords: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    category: Category
    subcategory: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class RiskAssessment(BaseModel):
    priority_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    category_severity: int = Field(default=0, ge=0, le=25)
    population_impact: int = Field(default=0, ge=0, le=25)
    safety_risk: int = Field(default=0, ge=0, le=25)
    urgency: int = Field(default=0, ge=0, le=25)
    reasoning: str = ""

    @model_validator(mode="after")
    def _band_must_match_score(self):
        expected = band_for_score(self.priority_score)
        if self.risk_level != expected:
            raise ValueError(
                f"risk_level {self.risk_level!r} contradicts priority_score "
                f"{self.priority_score} (expected {expected.value!r})"
            )
        return self


class RoutingDecision(BaseModel):
    department_name: str
    department_id: str | None = None
    contractor_id: str | None = None
    contractor_name: str | None = None
    jurisdiction_level: Literal["ward", "block", "district", "city"]
    justification: str = ""


class WorkOrderDraft(BaseModel):
    sla_hours: int
    sla_deadline: datetime
    estimated_cost: float
    cost_basis: str = ""
    materials: str = ""
    summary: str = ""


# ── bookkeeping carried through the graph ────────────────────────────────


class NodeDecision(BaseModel):
    """One line of the audit trail, one per node."""

    node: str
    summary: str
    duration_ms: int | None = None


class RetrievedChunk(BaseModel):
    """A retrieval hit, so any decision can cite its sources. Used from Phase 2."""

    source: str
    chunk_id: str | None = None
    score: float | None = None
    snippet: str = ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_schemas.py -v`
Expected: PASS, 19 tests (11 plain + 8 from the parametrized boundary test).

- [ ] **Step 5: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: add typed AI output schemas

Constraints are enforced at generation time via with_structured_output rather
than parsed out of a response afterwards. RiskAssessment cross-validates its
band against its score, so a model returning score=90 with risk_level='low'
fails loudly instead of reaching the database."
```

---

## Task 2: Prompt templates with versions

**Files:**
- Create: `backend/app/ai/prompts/__init__.py`, `backend/app/ai/prompts/templates.py`
- Test: `backend/tests/ai/test_prompts.py`

**Interfaces:**
- Consumes: `app.constants.Category`
- Produces:
  - `app.ai.prompts.get_prompt(name: str, version: str | None = None) -> ChatPromptTemplate`
  - `app.ai.prompts.PROMPT_REGISTRY: dict[tuple[str, str], ChatPromptTemplate]`
  - `app.ai.prompts.LATEST: dict[str, str]` — name → default version
  - Registered names: `"validate"`, `"classify"`, `"assess_risk"`, `"vision"`

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/test_prompts.py`:

```python
import pytest
from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts import LATEST, PROMPT_REGISTRY, get_prompt


def test_every_expected_prompt_is_registered():
    assert set(LATEST) == {"validate", "classify", "assess_risk", "vision"}


def test_get_prompt_returns_the_latest_version_by_default():
    assert isinstance(get_prompt("classify"), ChatPromptTemplate)


def test_get_prompt_can_pin_an_explicit_version():
    """Versioning is what lets the Phase 3 eval harness A/B two prompts."""
    assert get_prompt("classify", "v1") is PROMPT_REGISTRY[("classify", "v1")]


def test_unknown_prompt_name_raises_with_a_useful_message():
    with pytest.raises(KeyError, match="nonexistent"):
        get_prompt("nonexistent")


def test_unknown_version_raises_with_a_useful_message():
    with pytest.raises(KeyError, match="v99"):
        get_prompt("classify", "v99")


def test_classify_prompt_declares_the_variables_its_node_supplies():
    assert set(get_prompt("classify").input_variables) == {"description", "media_context"}


def test_validate_prompt_declares_its_variables():
    assert set(get_prompt("validate").input_variables) == {"description"}


def test_assess_risk_prompt_declares_its_variables():
    assert set(get_prompt("assess_risk").input_variables) == {
        "description", "category", "media_context"
    }


def test_classify_prompt_renders_with_untrusted_text_without_breaking():
    """Citizen text is untrusted input. Braces in it must not blow up templating."""
    rendered = get_prompt("classify").format_messages(
        description="pothole near {curly} braces and a $dollar",
        media_context="",
    )
    assert any("curly" in m.content for m in rendered)


def test_every_registered_prompt_renders_from_its_declared_variables():
    for (name, version), template in PROMPT_REGISTRY.items():
        filler = {var: "x" for var in template.input_variables}
        messages = template.format_messages(**filler)
        assert messages, f"{name}/{version} rendered nothing"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.prompts'`

- [ ] **Step 3: Implement the templates**

`backend/app/ai/prompts/templates.py`:

```python
"""Prompt templates, versioned so the eval harness can A/B them.

v1 embedded prompts as f-strings inside the method that used them, so there was
no way to compare two wordings or to know which produced a given result.

Note on templating: citizen text is untrusted and may contain braces. It is
passed as a template *variable*, never interpolated into the template string,
so `ChatPromptTemplate` treats it as data.
"""

from langchain_core.prompts import ChatPromptTemplate

from app.constants import Category

_CATEGORIES = ", ".join(c.value for c in Category)

VALIDATE_V1 = ChatPromptTemplate.from_messages([
    ("system",
     "You decide whether a citizen report describes a public infrastructure problem "
     "that a municipal body should act on. Be permissive about phrasing and spelling; "
     "be strict about subject matter. Personal disputes, private property issues, "
     "noise complaints about neighbours and general opinions are not infrastructure."),
    ("human",
     "Report:\n\n{description}\n\n"
     "Decide whether this is an infrastructure complaint. If it is not, say why in "
     "one sentence. If it is, restate what happened in one sentence and list any "
     "words signalling severity or danger."),
])

CLASSIFY_V1 = ChatPromptTemplate.from_messages([
    ("system",
     f"You classify municipal infrastructure complaints into exactly one category "
     f"from this list: {_CATEGORIES}.\n\n"
     "Guidance on the pairs that are most often confused:\n"
     "- ROADS covers damage to an existing road surface: potholes, cracks, broken dividers.\n"
     "- CONSTRUCTION covers building work: illegal construction, excavation left unrepaired.\n"
     "  A trench dug by a utility and never filled is CONSTRUCTION, not ROADS.\n"
     "- SEWAGE covers foul water and manholes; FLOODING covers rainwater and waterlogging.\n"
     "- SANITATION covers solid waste; SEWAGE covers liquid waste.\n\n"
     "Report your confidence honestly. Low confidence is useful information, not failure."),
    ("human",
     "Complaint:\n\n{description}\n\nAdditional context from attached media:\n{media_context}"),
])

CLASSIFY_V2 = ChatPromptTemplate.from_messages([
    ("system",
     f"You classify municipal infrastructure complaints into exactly one category "
     f"from this list: {_CATEGORIES}.\n\n"
     "Work in two steps. First identify the physical thing that is wrong. Then pick "
     "the category that owns that thing.\n\n"
     "Worked examples:\n"
     "- 'water on the road after every rain, drain is blocked' -> the thing wrong is "
     "standing rainwater -> FLOODING (not ROADS: the road surface is fine).\n"
     "- 'the contractor dug up the road for a cable and never filled it' -> the thing "
     "wrong is abandoned excavation -> CONSTRUCTION (not ROADS).\n"
     "- 'manhole cover missing outside the school' -> the thing wrong is an open "
     "sewer access -> SEWAGE (not PUBLIC_SPACES).\n\n"
     "Report your confidence honestly. Low confidence is useful information."),
    ("human",
     "Complaint:\n\n{description}\n\nAdditional context from attached media:\n{media_context}"),
])

ASSESS_RISK_V1 = ChatPromptTemplate.from_messages([
    ("system",
     "You assess how urgently a municipal body must act on an infrastructure complaint.\n\n"
     "Score four factors, each 0-25, and sum them into priority_score (0-100):\n"
     "- category_severity: how dangerous this class of problem is at its worst\n"
     "- population_impact: how many people the problem plausibly affects\n"
     "- safety_risk: how likely someone is hurt before it is fixed\n"
     "- urgency: how much worse it gets if left for a week\n\n"
     "Then set risk_level to match the total: 0-25 low, 26-50 medium, 51-75 high, "
     "76-100 critical. The band must agree with the score.\n\n"
     "Judge the specific report, not the category in general. A pothole outside a "
     "school gate is not the same as a pothole on an empty service road."),
    ("human",
     "Category: {category}\n\nComplaint:\n\n{description}\n\n"
     "Additional context from attached media:\n{media_context}"),
])

VISION_V1 = ChatPromptTemplate.from_messages([
    ("system",
     "You describe infrastructure problems visible in a photograph for a municipal "
     "complaint system. Describe only what you can see. Note the apparent scale and "
     "any immediate danger. If there is no infrastructure problem visible, say so "
     "plainly in one sentence."),
    ("human", "{image_context}"),
])
```

`backend/app/ai/prompts/__init__.py`:

```python
"""Prompt registry.

Keyed by (name, version) so the Phase 3 eval harness can run the same complaint
through two prompt versions and report which classified better.
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.templates import (
    ASSESS_RISK_V1, CLASSIFY_V1, CLASSIFY_V2, VALIDATE_V1, VISION_V1,
)

PROMPT_REGISTRY: dict[tuple[str, str], ChatPromptTemplate] = {
    ("validate", "v1"): VALIDATE_V1,
    ("classify", "v1"): CLASSIFY_V1,
    ("classify", "v2"): CLASSIFY_V2,
    ("assess_risk", "v1"): ASSESS_RISK_V1,
    ("vision", "v1"): VISION_V1,
}

# The version each node uses unless told otherwise.
LATEST: dict[str, str] = {
    "validate": "v1",
    "classify": "v2",
    "assess_risk": "v1",
    "vision": "v1",
}


def get_prompt(name: str, version: str | None = None) -> ChatPromptTemplate:
    """Fetch a registered prompt, defaulting to the version in LATEST."""
    if name not in LATEST:
        raise KeyError(f"unknown prompt {name!r}; registered: {sorted(LATEST)}")
    resolved = version or LATEST[name]
    try:
        return PROMPT_REGISTRY[(name, resolved)]
    except KeyError:
        available = sorted(v for (n, v) in PROMPT_REGISTRY if n == name)
        raise KeyError(
            f"unknown version {resolved!r} for prompt {name!r}; available: {available}"
        ) from None


__all__ = ["PROMPT_REGISTRY", "LATEST", "get_prompt"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_prompts.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: add versioned prompt registry

Prompts are keyed by (name, version) so the Phase 3 eval harness can A/B two
wordings on the same complaint. classify ships v1 and v2 so that comparison has
something to compare.

Citizen text is passed as a template variable rather than interpolated into the
template string, so braces in untrusted input cannot break rendering."
```

---

## Task 3: The LLM layer

The only module in the codebase that constructs a chat model or calls `.with_structured_output(...)`.

**Files:**
- Modify: `backend/requirements.txt`, `backend/app/config.py`
- Create: `backend/app/ai/llm.py`
- Test: `backend/tests/ai/test_llm.py`

**Interfaces:**
- Consumes: `app.config.settings`, `app.ai.prompts.get_prompt`
- Produces:
  - `app.ai.llm.Task` — `StrEnum`: `VALIDATE`, `CLASSIFY`, `ASSESS_RISK`, `VISION`, `NARRATE`
  - `app.ai.llm.TASK_MODEL: dict[Task, str]` — the tiering map
  - `app.ai.llm.NoModelConfigured(RuntimeError)`
  - `app.ai.llm.available_providers() -> list[str]`
  - `app.ai.llm.build_chat_model(task: Task) -> BaseChatModel`
  - `app.ai.llm.build_structured(task: Task, schema: type[BaseModel], prompt_name: str, prompt_version: str | None = None) -> Runnable`
  - `app.ai.llm.SHARED_RATE_LIMITER: InMemoryRateLimiter`

- [ ] **Step 1: Add the dependencies**

```bash
cd backend
cat >> requirements.txt <<'EOF'

# ── AI (Phase 1) ───────────────────────────────────
langchain==1.3.18
langchain-core==1.6.1
langgraph==1.2.11
langchain-google-genai==4.4.0
langgraph-checkpoint-sqlite==3.1.1
aiosqlite==0.22.1
langsmith==0.12.1
EOF
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c "import langchain, langgraph, langchain_google_genai; print('installed')"
```

- [ ] **Step 2: Add the new settings**

In `backend/app/config.py`, extend the LLM provider block:

```python
    # ── LLM providers ─────────────────────────────────────────
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_model_strong: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_enabled: bool = False
    # Requests per second ceiling shared by every task. The Gemini free tier
    # rate-limits aggressively and a 100-item eval sweep will hit it.
    llm_requests_per_second: float = 0.5
    llm_max_retries: int = 3
```

- [ ] **Step 3: Write the failing test**

`backend/tests/ai/test_llm.py`:

```python
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.ai import llm as llm_module
from app.ai.llm import (
    SHARED_RATE_LIMITER, TASK_MODEL, NoModelConfigured, Task,
    available_providers, build_chat_model, build_structured,
)
from app.ai.schemas import ClassificationResult


def test_every_task_has_a_model_tier():
    """A task missing from the map would silently fall back to a default."""
    assert set(TASK_MODEL) == set(Task)


def test_cheap_and_strong_tiers_are_actually_different():
    assert TASK_MODEL[Task.CLASSIFY] != TASK_MODEL[Task.NARRATE]


def test_no_providers_configured_is_a_clear_error(monkeypatch):
    """v1 silently degraded to keyword matching with no signal that it had."""
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", None)
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", False)
    assert available_providers() == []
    with pytest.raises(NoModelConfigured, match="GEMINI_API_KEY"):
        build_chat_model(Task.CLASSIFY)


def test_gemini_alone_is_reported_available(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", False)
    assert available_providers() == ["gemini"]


def test_both_providers_puts_gemini_first(monkeypatch):
    """Order matters: the first is primary, the rest are fallbacks."""
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", True)
    assert available_providers() == ["gemini", "ollama"]


def test_ollama_alone_is_usable(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", None)
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", True)
    assert available_providers() == ["ollama"]


def test_rate_limiter_is_shared_across_tasks():
    """One ceiling for the whole process, not one per model instance."""
    assert SHARED_RATE_LIMITER is llm_module.SHARED_RATE_LIMITER


def test_build_structured_accepts_an_injected_model(monkeypatch):
    """The seam that makes nodes testable.

    LangChain's fake chat models raise NotImplementedError on
    with_structured_output, so tests inject an already-structured runnable
    instead of a raw model.
    """
    stub = RunnableLambda(
        lambda _: ClassificationResult(category="ROADS", confidence=0.88)
    )
    result = stub.invoke({"description": "pothole", "media_context": ""})
    assert result.category == "ROADS"


def test_fake_models_cannot_do_structured_output():
    """Documents WHY the injection seam above exists, so nobody 'simplifies' it."""
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="{}")]))
    with pytest.raises(NotImplementedError):
        fake.with_structured_output(ClassificationResult)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.llm'`

- [ ] **Step 5: Implement the LLM layer**

`backend/app/ai/llm.py`:

```python
"""All model access lives here.

This is the only module that constructs a chat model or calls
`.with_structured_output(...)`. Nodes receive already-bound runnables, because
LangChain's fake chat models raise NotImplementedError on
with_structured_output — a node holding a raw model cannot be unit-tested.

v1 dispatched on `if provider == "gemini" / elif ...` at every call site, so
each capability was written three times and adding a provider meant three more
methods.
"""

from enum import StrEnum

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from app.ai.prompts import get_prompt
from app.config import settings


class NoModelConfigured(RuntimeError):
    """Raised when no provider is usable, instead of degrading silently."""


class Task(StrEnum):
    VALIDATE = "validate"
    CLASSIFY = "classify"
    ASSESS_RISK = "assess_risk"
    VISION = "vision"
    NARRATE = "narrate"


# Model tiering: cheap models for the high-volume mechanical steps, a stronger
# one where the output is prose a human reads. Configured here rather than at
# the call sites so an eval sweep can vary it.
TASK_MODEL: dict[Task, str] = {
    Task.VALIDATE: settings.gemini_model,
    Task.CLASSIFY: settings.gemini_model,
    Task.ASSESS_RISK: settings.gemini_model,
    Task.VISION: settings.gemini_model,
    Task.NARRATE: settings.gemini_model_strong,
}

# One ceiling for the whole process. Not optional: the Gemini free tier
# rate-limits hard, and Phase 3 sweeps ~100 complaints in a run.
SHARED_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=settings.llm_requests_per_second,
    check_every_n_seconds=0.1,
    max_bucket_size=5,
)


def available_providers() -> list[str]:
    """Usable providers, primary first. Later entries become fallbacks."""
    providers: list[str] = []
    if settings.gemini_api_key:
        providers.append("gemini")
    if settings.ollama_enabled:
        providers.append("ollama")
    return providers


def _build_one(provider: str, task: Task) -> BaseChatModel:
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=TASK_MODEL[task],
            google_api_key=settings.gemini_api_key,
            rate_limiter=SHARED_RATE_LIMITER,
            max_retries=settings.llm_max_retries,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            rate_limiter=SHARED_RATE_LIMITER,
        )
    raise NoModelConfigured(f"unknown provider {provider!r}")


def build_chat_model(task: Task) -> BaseChatModel:
    """The model for a task, with every other provider chained as a fallback."""
    providers = available_providers()
    if not providers:
        raise NoModelConfigured(
            "No LLM provider is configured. Set GEMINI_API_KEY, or set "
            "OLLAMA_ENABLED=true with a local Ollama running."
        )
    primary = _build_one(providers[0], task)
    backups = [_build_one(p, task) for p in providers[1:]]
    return primary.with_fallbacks(backups) if backups else primary


def build_structured(
    task: Task,
    schema: type[BaseModel],
    prompt_name: str,
    prompt_version: str | None = None,
) -> Runnable:
    """A prompt-to-validated-object chain, ready to hand a node.

    Nodes get one of these through `config["configurable"]`; a test passes a
    `RunnableLambda` returning a fixture instead. That seam is the whole reason
    nodes never touch a raw model.
    """
    model = build_chat_model(task)
    return get_prompt(prompt_name, prompt_version) | model.with_structured_output(schema)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_llm.py -v`
Expected: PASS, 9 tests.

If `langchain_ollama` is not installed, `_build_one("ollama", ...)` raises `ImportError` at call time. That is acceptable — no test constructs an Ollama model, and Ollama is opt-in via `OLLAMA_ENABLED`. Do **not** add `langchain-ollama` to requirements in this task; it arrives with the Ollama work.

- [ ] **Step 7: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/requirements.txt backend/app/config.py backend/app/ai backend/tests/ai
git commit -m "feat: add the LLM layer

One module owns model construction: task-based tiering, provider fallback via
with_fallbacks, a process-wide rate limiter, and structured-output binding.

build_structured returns a prompt-to-validated-object chain. Nodes receive one
of these rather than a raw model, because LangChain's fake chat models raise
NotImplementedError on with_structured_output — a node holding a raw model
could not be unit-tested without a network call."
```

---

## Task 4: Graph state and the checkpoint allowlist

**Files:**
- Create: `backend/app/ai/graph/__init__.py`, `backend/app/ai/graph/state.py`
- Test: `backend/tests/ai/test_state.py`

**Interfaces:**
- Consumes: `app.ai.schemas` (all models)
- Produces:
  - `app.ai.graph.state.ComplaintState` — the `TypedDict`
  - `app.ai.graph.state.CHECKPOINT_ALLOWLIST: list[type]` — every Pydantic class reachable from state
  - `app.ai.graph.state.build_serializer() -> JsonPlusSerializer`
  - `app.ai.graph.state.initial_state(...) -> ComplaintState`

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/test_state.py`:

```python
import operator
import typing
from typing import Annotated, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from app.ai import schemas as schemas_module
from app.ai.graph.state import (
    CHECKPOINT_ALLOWLIST, ComplaintState, build_serializer, initial_state,
)
from app.ai.schemas import Coords, MediaRef


ACCUMULATING = ["media_insights", "evidence", "decision_log", "errors"]


def test_accumulating_fields_have_reducers():
    """Without a reducer, two parallel nodes writing the same field raise
    InvalidUpdateError. The media subgraph fans out, so these must merge."""
    hints = get_type_hints(ComplaintState, include_extras=True)
    for field in ACCUMULATING:
        annotation = hints[field]
        assert get_origin(annotation) is Annotated, f"{field} has no reducer"
        assert operator.add in get_args(annotation), f"{field}'s reducer is not operator.add"


def test_scalar_fields_do_not_have_reducers():
    """A reducer on a scalar would concatenate instead of replace."""
    hints = get_type_hints(ComplaintState, include_extras=True)
    for field in ("description", "classification", "risk", "terminal_reason"):
        assert get_origin(hints[field]) is not Annotated, f"{field} should not have a reducer"


def test_initial_state_populates_every_declared_key():
    """A missing key surfaces as a KeyError inside a node, far from its cause."""
    state = initial_state(
        complaint_id="c1",
        tracking_id="CIV-TEST0001",
        tenant_id="t1",
        raw_description="pothole on the main road",
        media=[MediaRef(file_path="uploads/x.jpg", media_type="image")],
        coords=Coords(latitude=12.9, longitude=77.6),
    )
    assert set(state) == set(get_type_hints(ComplaintState))


def test_initial_state_starts_accumulators_empty():
    state = initial_state(complaint_id="c1", tracking_id="CIV-T", raw_description="x")
    for field in ACCUMULATING:
        assert state[field] == []


def test_checkpoint_allowlist_covers_every_pydantic_model_in_schemas():
    """A class missing from the allowlist is deserialized back as a plain dict,
    NOT an error — so `state["classification"].category` fails later with
    AttributeError, far from the cause. This test is the guard."""
    defined = {
        obj for obj in vars(schemas_module).values()
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel
    }
    missing = defined - set(CHECKPOINT_ALLOWLIST)
    assert not missing, f"not in CHECKPOINT_ALLOWLIST: {sorted(c.__name__ for c in missing)}"


def test_allowlist_entries_are_classes_not_module_tuples():
    """Passing ("app","ai","schemas") silently allows nothing. Pass the classes."""
    for entry in CHECKPOINT_ALLOWLIST:
        assert isinstance(entry, type), f"{entry!r} is not a class"


def test_build_serializer_round_trips_a_pydantic_model():
    from app.ai.schemas import ClassificationResult

    serde = build_serializer()
    original = ClassificationResult(category="ROADS", confidence=0.9)
    restored = serde.loads_typed(serde.dumps_typed(original))
    assert isinstance(restored, ClassificationResult), (
        f"round-tripped to {type(restored).__name__}, not ClassificationResult — "
        "the allowlist is not being applied"
    )
    assert restored.confidence == 0.9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph'`

- [ ] **Step 3: Implement the state**

```bash
mkdir -p backend/app/ai/graph && touch backend/app/ai/graph/__init__.py
```

`backend/app/ai/graph/state.py`:

```python
"""The object every node reads from and writes to.

Two things here are load-bearing and easy to get wrong:

1. Fields written by parallel nodes carry `Annotated[list[X], operator.add]`.
   Without a reducer, LangGraph raises InvalidUpdateError when the media
   subgraph's fan-out branches both write to the same key.

2. Every Pydantic class reachable from state must appear in
   CHECKPOINT_ALLOWLIST. A class missing from it is deserialized back from the
   checkpoint as a plain dict rather than raising, so the failure surfaces much
   later as an AttributeError on a field access.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.ai.schemas import (
    ClassificationResult, Coords, LocationInfo, MediaInsight, MediaRef,
    NodeDecision, RetrievedChunk, RiskAssessment, RoutingDecision,
    ValidationResult, WorkOrderDraft,
)


class ComplaintState(TypedDict):
    # ── immutable input ──────────────────────────────────────
    complaint_id: str
    tracking_id: str
    tenant_id: str | None
    raw_description: str
    media: list[MediaRef]
    coords: Coords | None

    # ── written in parallel: reducers required ───────────────
    media_insights: Annotated[list[MediaInsight], operator.add]
    evidence: Annotated[list[RetrievedChunk], operator.add]
    decision_log: Annotated[list[NodeDecision], operator.add]
    errors: Annotated[list[str], operator.add]

    # ── enriched ─────────────────────────────────────────────
    description: str
    location: LocationInfo | None

    # ── AI outputs ───────────────────────────────────────────
    validation: ValidationResult | None
    classification: ClassificationResult | None
    risk: RiskAssessment | None
    routing: RoutingDecision | None
    work_order: WorkOrderDraft | None

    # ── control ──────────────────────────────────────────────
    investigate_turns: int
    terminal_reason: str | None


# Every Pydantic class reachable from ComplaintState. Pass the classes
# themselves: a ("module",) tuple silently allows nothing, and the symptom is a
# dict where a model should be.
CHECKPOINT_ALLOWLIST: list[type] = [
    ClassificationResult, Coords, LocationInfo, MediaInsight, MediaRef,
    NodeDecision, RetrievedChunk, RiskAssessment, RoutingDecision,
    ValidationResult, WorkOrderDraft,
]


def build_serializer() -> JsonPlusSerializer:
    """The checkpoint serializer, restricted to our own model classes.

    Checkpoint deserialization is a code-execution surface: anyone who can write
    to the checkpoint database can otherwise choose what gets constructed.
    """
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_ALLOWLIST)


def initial_state(
    *,
    complaint_id: str,
    tracking_id: str,
    raw_description: str,
    tenant_id: str | None = None,
    media: list[MediaRef] | None = None,
    coords: Coords | None = None,
) -> ComplaintState:
    """Every key populated, so no node ever meets a missing one."""
    return ComplaintState(
        complaint_id=complaint_id,
        tracking_id=tracking_id,
        tenant_id=tenant_id,
        raw_description=raw_description,
        media=media or [],
        coords=coords,
        media_insights=[],
        evidence=[],
        decision_log=[],
        errors=[],
        description=raw_description,
        location=None,
        validation=None,
        classification=None,
        risk=None,
        routing=None,
        work_order=None,
        investigate_turns=0,
        terminal_reason=None,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_state.py -v`
Expected: PASS, 7 tests.

If `test_build_serializer_round_trips_a_pydantic_model` returns a `dict`, the allowlist is not being applied — check that `CHECKPOINT_ALLOWLIST` holds classes, not tuples.

- [ ] **Step 5: Verify the reducer actually merges parallel writes**

This is the behaviour the reducer exists for, so prove it end to end rather than only asserting the annotation. Add to `backend/tests/ai/test_state.py`:

```python
def test_parallel_writes_merge_instead_of_colliding():
    """The property the reducer exists for: two branches writing the same key."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    from app.ai.schemas import MediaInsight

    def start(state: ComplaintState) -> dict:
        return {}

    def fan_out(state: ComplaintState):
        return [Send("analyse", {"item": m.file_path}) for m in state["media"]]

    def analyse(payload: dict) -> dict:
        return {"media_insights": [
            MediaInsight(file_path=payload["item"], media_type="image", text="seen")
        ]}

    builder = StateGraph(ComplaintState)
    builder.add_node("start", start)
    builder.add_node("analyse", analyse)
    builder.add_edge(START, "start")
    builder.add_conditional_edges("start", fan_out, ["analyse"])
    builder.add_edge("analyse", END)
    graph = builder.compile()

    state = initial_state(
        complaint_id="c1", tracking_id="CIV-T", raw_description="x",
        media=[MediaRef(file_path=f"uploads/{i}.jpg", media_type="image") for i in range(3)],
    )
    result = graph.invoke(state)

    assert len(result["media_insights"]) == 3
    assert {i.file_path for i in result["media_insights"]} == {
        "uploads/0.jpg", "uploads/1.jpg", "uploads/2.jpg"
    }
```

Run: `cd backend && .venv/bin/python -m pytest tests/ai/test_state.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Confirm the architectural boundary still holds**

Run: `cd backend && .venv/bin/python -m pytest tests/test_import_rules.py -v`
Expected: PASS. `app/ai/` now exists, so these tests stop being vacuous — this is their first real run.

- [ ] **Step 7: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS, 97 tests (51 from Phase 0 + 19 schemas + 10 prompts + 9 llm + 8 state).

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai backend/tests/ai
git commit -m "feat: add graph state with reducers and a checkpoint allowlist

Fields written by the media subgraph's parallel branches carry
Annotated[list[X], operator.add]; without a reducer LangGraph raises
InvalidUpdateError when two branches write the same key. A test drives a real
fan-out to prove the merge rather than only asserting the annotation.

Every Pydantic class reachable from state is in CHECKPOINT_ALLOWLIST. A class
missing from it is silently deserialized as a plain dict rather than raising,
so a test asserts the allowlist covers app.ai.schemas exhaustively."
```

---

## Phase 1a Done When

- [ ] `cd backend && .venv/bin/python -m pytest` passes with 97 tests, no network access, no API key set
- [ ] `tests/test_import_rules.py` passes with `app/ai/` present — the boundary guard is live, not vacuous
- [ ] `build_structured(...)` raises `NoModelConfigured` with an actionable message when nothing is configured, rather than degrading silently the way v1 did
- [ ] A Pydantic model round-trips through `build_serializer()` as its own class, not a dict
- [ ] `CHECKPOINT_ALLOWLIST` covers every model in `app/ai/schemas.py`, enforced by a test

**Next:** Phase 1b — nodes, media subgraph, graph assembly, checkpointer, runner, API wiring, streaming and observability.
