# Phase 2c — Semantic Clusters, Grounded Briefing, Email Draft

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The three background responsibilities v1 owned and v2 has not yet rebuilt all run: complaints that describe the same problem in the same place group into one work order by meaning rather than by a rounded coordinate, the officer's daily briefing is real narrative grounded in the day's numbers and the SLA policy (v1's has *never* produced anything but template text), and the department email is drafted by a structured chain that cites the SOP. Phase 2c also closes the three correctness seams Phase 2b left open, because the new chains would otherwise inherit them.

**Architecture:** No graph changes — nothing here runs per complaint. Three services under `app/services/` (`clustering.py`, `briefing.py`, `email_draft.py`), each a pure-Python core with the model and the retriever injected, plus three jobs registered on the Phase 2b `AsyncIOScheduler`. Clustering embeds open complaints with the Phase 2a `Embedder` and groups by cosine similarity *within* a haversine radius; it is the only new numeric algorithm in the phase and it lives in functions that take lists and return lists, so it is tested without a database. The briefing and the email draft are `build_structured` chains with prompts registered in the Phase 1a registry, retrieving with the `doc_type` filters Phase 2b established. Every job is idempotent on a database marker, as the SLA monitor is.

**Tech Stack:** numpy (cosine over the existing 768-d embeddings), APScheduler 3.10 (`AsyncIOScheduler`, added in Phase 2b), LangChain structured output, FAISS + rank-bm25 via Phase 2a, SQLAlchemy 2, Alembic, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-02-civicai-v2-design.md` §3.5 (background workflows), §3.6 (retained features — the officer email-draft flow), §4.2, §11 criteria 3 and 5. Read the **"Carried forward from Phase 2b"** section at the end of `docs/superpowers/plans/2026-09-15-phase2b-grounded-nodes.md` first: Tasks 1–3 below exist to close items on it.

**Prior phases:** 0 (foundation), 1a (AI layer), 1b (graph), 1c (HTTP + streaming), 2a (RAG), 2b (grounded nodes, cases, cache, SLA monitor) — **376 tests green, no network, ~5s**.

## Global Constraints

- Python 3.14, `backend/.venv`. Run tests as `cd backend && .venv/bin/python -m pytest -q`. Suite starts at **376 passing, no network**. Every task keeps it green and adds the count it states.
- **No network in tests, ever.** Clustering tests use `FakeEmbedder`; chain tests use a `RunnableLambda`; retrieval tests use the `FakeRetriever` in `tests/ai/graph/test_retrieval.py`.
- **A job is a function that takes what it needs.** `session_factory`, `send`, `chain`, `retriever`, `embedder` and `now` are all parameters with production defaults, the way `check_sla_deadlines` does it. A test never monkeypatches a module global to control a job.
- **Every job is idempotent, and a test proves it by calling the job twice.** The marker is a database row, never a process variable: `DailyBriefing` for the briefing (one per tenant per day), `Complaint.cluster_id` for clustering, `Complaint.email_draft` for the draft. Phase 2b's `Notification.dedupe_key` pattern stands where an email is sent.
- **No new hardcoded intelligence.** Anything a municipality would argue about — the bulk discount for grouped work, the SLA window per risk band — comes from a retrieved document or the tenant's own config, never a dict in a module. This phase *deletes* the last such dict (`SLA_HOURS`).
- **A failed model call degrades visibly.** v1's briefing served template text for its entire life while recording nothing. Every fallback path here sets a persisted flag (`DailyBriefing.is_fallback`) and logs at `warning`.
- Prompts fence retrieved text in `<evidence>`, citizen text in `<report>`, and instruct the model to cite `[n]`. New prompts are registered in `app/ai/prompts/__init__.py` with a `LATEST` entry, and `tests/ai/test_prompts.py::test_every_expected_prompt_is_registered` is updated in the same task.
- `app/ai/` must never import `app/api/`. `app/services/` may import `app/ai/`, not the reverse.
- Commit messages: imperative subject, body explains why. **No `Co-Authored-By` or any other trailer line** — the repository owner has forbidden it. Verify with `git log -1 --format=%B | grep -ci co-authored` → `0`.
- A docstring on every module saying what it is for and why; a comment on every non-obvious line; readable by an intermediate Python programmer.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/app/ai/rag/cases.py` (modify) | `tenant_id` in case metadata |
| `backend/app/ai/graph/nodes/assess_risk.py` (modify) | filter precedent by tenant, not category alone |
| `backend/app/ai/llm.py` (modify) | cache keyed on `(prompt_name, version)`; `Task.BRIEFING`, `Task.EMAIL_DRAFT` |
| `backend/app/ai/graph/nodes/work_order.py` (modify) | `SLA_HOURS` deleted; window from the tenant config, SLA policy cited |
| `backend/app/services/tenancy.py` (modify) | `sla_hours_for(tenant, risk_level)` — the one reader of `Tenant.config["sla_hours"]` |
| `backend/app/db/models/complaint.py` + migration | `Complaint.cluster_id` |
| `backend/app/services/clustering.py` (create) | `haversine_km`, `cosine`, `cluster_candidates`, `detect_clusters` |
| `backend/app/services/briefing.py` (create) | `gather_stats`, `generate_briefing` |
| `backend/app/services/email_draft.py` (create) | `draft_department_email` |
| `backend/app/ai/schemas.py` (modify) | `BriefingNarrative`, `EmailDraft` |
| `backend/app/ai/prompts/templates.py`, `__init__.py` (modify) | `BRIEFING_V1`, `EMAIL_DRAFT_V1`, `WORK_ORDER_CLUSTER_V1` |
| `backend/app/ai/rag/corpus/rate_card.md` (modify) | a "Grouped work at multiple sites" section — the bulk rule must be *in the document* |
| `backend/app/services/scheduler.py` (modify) | `cluster_detection` hourly, `daily_briefing` 08:00, `cases_refresh` daily |
| `backend/app/config.py`, `.env.example` (modify) | cluster radius/threshold/min size, briefing hour, job toggles |

---

### Task 1: Tenant-scoped precedent and a version-keyed cache

Two corrections from Phase 2b's carry-forward, done first because Tasks 5–7 add chains and retrieval that would copy both mistakes.

**Files:**
- Modify: `app/ai/rag/cases.py`, `app/ai/graph/nodes/assess_risk.py`, `app/ai/llm.py`
- Test: `tests/ai/rag/test_cases.py` (append), `tests/ai/graph/test_assess_risk.py` (append), `tests/ai/test_cache.py` (append)

**Interfaces:**
- `case_record_metadata(complaint)` gains `"tenant_id": complaint.tenant_id`.
- `assess_risk_node` retrieves precedent with `filters={"category": category, "tenant_id": state["tenant_id"]}`. A complaint with no `tenant_id` retrieves **no** precedent and records no error — the same fail-closed rule `route_node` applies, for the same reason: an unscoped query spans every tenant.
- `cache_for(prompt_name)` becomes `cache_for(prompt_name, version=None)`, resolving the version through `LATEST` and keying `_CACHES` on the resolved `(name, version)` tuple.

- [ ] **Step 1: Write the failing tests**

In `tests/ai/rag/test_cases.py`, add a second tenant and assert the leak is closed. `_resolved` currently calls `seed_database`, which returns the existing tenant on a second call, so the test builds its second tenant directly:

```python
def test_precedent_does_not_cross_tenants(db_session, tmp_path):
    from app.db.models.core import Tenant

    complaint, _ = _resolved(db_session, description="Deep pothole near the school gate")
    other = Tenant(name="Mysuru City Corporation", config={})
    db_session.add(other)
    db_session.flush()
    stray = Complaint(tracking_id="CIV-OTHER001", tenant_id=other.id, citizen_email="a@b.com",
                      description="Deep pothole near the school gate", category="ROADS",
                      district="East", risk_level="high", status="resolved")
    db_session.add(stray)
    db_session.flush()
    order = WorkOrder(complaint_id=stray.id, tenant_id=other.id, status="completed", sla_hours=24,
                      actual_cost=9000.0, created_at=utcnow() - timedelta(hours=9), completed_at=utcnow())
    db_session.add(order)
    db_session.commit()

    ingest_cases(embedder=FakeEmbedder(), index_dir=tmp_path / "cases", session_factory=lambda: db_session)
    retriever = load_cases_retriever(embedder=FakeEmbedder(), index_dir=tmp_path / "cases")
    hits = retriever.search("pothole", k=5, fetch_k=200, filters={"tenant_id": complaint.tenant_id})
    assert hits
    assert all(h.chunk.metadata["tenant_id"] == complaint.tenant_id for h in hits)
```

In `tests/ai/graph/test_assess_risk.py`:

```python
def test_precedent_is_filtered_to_the_complaint_tenant(make_config, base_state):
    cases = FakeRetriever([_hit("ROADS in East: resolved in 5 hours, Rs 6,300.", "case:1", tenant_id="t-1")])
    state = {**base_state, "tenant_id": "t-1",
             "classification": ClassificationResult(category=Category.ROADS, confidence=0.9)}
    config = make_config(risk_chain=returns(RiskAssessment(priority_score=60, risk_level=RiskLevel.HIGH)),
                        policy_retriever=FakeRetriever(), cases_retriever=cases)
    assess_risk_node(state, config)
    case_calls = [c for c in cases.calls if c["filters"]]
    assert case_calls and case_calls[0]["filters"] == {"category": "ROADS", "tenant_id": "t-1"}


def test_a_tenantless_complaint_retrieves_no_precedent(make_config, base_state):
    """Fail closed, as route_node does: an unscoped query spans every tenant."""
    cases = FakeRetriever([_hit("ROADS in East: resolved in 5 hours.", "case:1", tenant_id="t-1")])
    state = {**base_state, "tenant_id": None,
             "classification": ClassificationResult(category=Category.ROADS, confidence=0.9)}
    config = make_config(risk_chain=returns(RiskAssessment(priority_score=60, risk_level=RiskLevel.HIGH)),
                        policy_retriever=FakeRetriever(), cases_retriever=cases)
    update = assess_risk_node(state, config)
    assert cases.calls == []
    assert update["risk"] is not None, "no precedent must not stop the assessment"
```

In `tests/ai/test_cache.py`:

```python
def test_two_prompt_versions_do_not_share_a_cache(monkeypatch):
    """A Phase 3 sweep A/Bs classify v1 against v2 in one process. Sharing one
    cache would serve v2's answer to v1's prompt and silently flatten the eval."""
    from app.ai import llm
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_cache_enabled", True)
    monkeypatch.setattr(llm, "_CACHES", {})
    monkeypatch.setattr("app.ai.rag.embeddings.build_embedder", lambda: FakeEmbedder())
    assert llm.cache_for("classify", "v1") is not llm.cache_for("classify", "v2")
    assert llm.cache_for("classify") is llm.cache_for("classify", "v2"), "the default resolves through LATEST"
```

- [ ] **Step 2: Run them and watch them fail** — `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_cases.py tests/ai/graph/test_assess_risk.py tests/ai/test_cache.py -q`. The cases test fails on a missing `tenant_id` key; the assess_risk tests fail on the filter dict; the cache test fails with a `TypeError` on the extra argument.

- [ ] **Step 3: Implement.** In `cases.py` add the key. In `assess_risk.py`, build the filter and guard on `state["tenant_id"]`:

```python
    tenant_id = state["tenant_id"]
    if deps.cases_retriever is not None and tenant_id is not None:
        cases = retrieve(deps.cases_retriever, state["description"], node="assess_risk", k=3,
                         filters={"category": category, "tenant_id": tenant_id})
```

In `llm.py`, resolve the version and key on the pair:

```python
def cache_for(prompt_name: str, version: str | None = None) -> "SemanticCache | None":
    """The cache for one prompt *version*, or None when caching is off or no
    embedder is configured. Keyed on the resolved version so an eval sweep
    comparing two versions in one process does not serve one for the other."""
    if not settings.semantic_cache_enabled:
        return None
    from app.ai.prompts import LATEST

    key = (prompt_name, LATEST[prompt_name] if version is None else version)
    ...
```

`build_deps` keeps calling `cache_for("classify")` etc. — the default resolution keeps it correct.

- [ ] **Step 4: Re-ingest note.** Adding a metadata key changes nothing about the chunk text, so `_sync_collection` will skip every case document as unchanged and the *old* metadata stays in the index. Add one line to `cases.py`'s module docstring saying that a metadata-only change requires `python -m app.ai.rag.ingest --collection cases` against a deleted index directory (or a `--force` flag, deliberately not built here), and state it in the commit body. This is the reason the tenant fix lands before any real data exists.

- [ ] **Step 5: Full suite** — expect **376 + 5 = 381**.

- [ ] **Step 6: Commit** — `fix: scope precedent retrieval to the tenant and key the cache on prompt version`.

---

### Task 2: The SLA window comes from the tenant, not from a dict

Spec §11 criterion 3 says no hardcoded lookup dictionary may remain in the decision path, and names SLA windows explicitly. Phase 2b deleted the cost dicts and left `SLA_HOURS` in `work_order.py` — the same numbers are already seeded into `Tenant.config["sla_hours"]` and written in `corpus/sla_policy.md`, so the value exists in three places and the code trusts the one nobody can edit.

**The window must stay deterministic** — it sets a legal-ish deadline and an email goes out about it. So this task does *not* ask a model for it. The tenant's own config is the source of truth, the SLA policy document is what the work order cites, and a corpus test asserts the two agree.

**Files:**
- Modify: `app/services/tenancy.py`, `app/ai/graph/nodes/work_order.py`, `app/services/seed.py` (only if the seeded config is missing a band)
- Test: `tests/services/test_tenancy.py` (append), `tests/ai/graph/test_work_order.py` (modify), `tests/ai/rag/test_corpus.py` (append)

**Interfaces:**
- `DEFAULT_SLA_HOURS: dict[RiskLevel, int]` lives in `tenancy.py` as the *fallback for a tenant whose config omits a band*, and the module docstring says it is a default, not a policy.
- `sla_hours_for(tenant, risk_level: RiskLevel) -> int` — reads `tenant.config["sla_hours"][risk_level.value]`, falls back to `DEFAULT_SLA_HOURS` with a `warning` log naming the tenant, and raises nothing.
- `work_order_node` takes the window from `deps.sla_hours(tenant_id, risk_level)` — a new `GraphDeps` field defaulting to a closure over `SessionLocal` in `build_deps`, so the node still performs no database access itself.

- [ ] **Step 1: Failing tests**

```python
# tests/services/test_tenancy.py
def test_sla_hours_come_from_the_tenant_config(db_session):
    seeded = seed_database(db_session)
    tenant = db_session.get(Tenant, seeded["tenant_id"])
    assert sla_hours_for(tenant, RiskLevel.CRITICAL) == 4
    assert sla_hours_for(tenant, RiskLevel.LOW) == 168


def test_a_missing_band_falls_back_and_says_so(db_session, caplog):
    tenant = Tenant(name="Sparse Council", config={"sla_hours": {"critical": 2}})
    db_session.add(tenant); db_session.flush()
    assert sla_hours_for(tenant, RiskLevel.CRITICAL) == 2
    with caplog.at_level("WARNING"):
        assert sla_hours_for(tenant, RiskLevel.HIGH) == DEFAULT_SLA_HOURS[RiskLevel.HIGH]
    assert "Sparse Council" in caplog.text or tenant.id in caplog.text
```

```python
# tests/ai/rag/test_corpus.py — the document and the seed must not drift
def test_the_sla_policy_states_the_same_windows_the_seed_configures(db_session):
    from app.services.tenancy import DEFAULT_SLA_HOURS

    text = next(t for p, t in load_corpus() if p.name == "sla_policy.md")
    for level, hours in DEFAULT_SLA_HOURS.items():
        assert f"{hours} hours" in text or f"{hours}h" in text, f"{level.value} window missing from the policy"
```

In `tests/ai/graph/test_work_order.py`, the tests that assert `sla_hours == 4` now inject the window: `make_config(..., sla_hours=lambda tenant_id, risk: 4)`. Add one test that the node asks for the window with the state's tenant and the assessed risk level, and one that a `sla_hours` callable raising does **not** lose the work order (fall back to `DEFAULT_SLA_HOURS`, record a soft error) — the same soft-dependency rule as retrieval.

- [ ] **Step 2: Watch them fail.** `grep -rn "SLA_HOURS" backend/app backend/tests` afterwards must only find `tenancy.py` and its tests.

- [ ] **Step 3: Implement**, deleting `SLA_HOURS` from `work_order.py` and importing nothing from `tenancy.py` into the node — the callable arrives through `GraphDeps`, like every other dependency.

- [ ] **Step 4: Full suite** — expect **381 + 5 = 386**. `tests/ai/rag/test_corpus.py` imports `SLA_HOURS` from `work_order.py` today (line 3); update that import.

- [ ] **Step 5: Commit** — `refactor: take the SLA window from the tenant config and cite the policy`.

---

### Task 3: Cluster membership on the complaint

**Files:**
- Modify: `app/db/models/complaint.py`, new Alembic revision
- Test: `tests/db/test_complaint_models.py` (append), `tests/db/test_migrations.py` (stays green)

`work_orders.complaint_id` is `unique=True` — a deliberate Phase 0 decision so `Complaint.work_order` (`uselist=False`) cannot silently return two rows. **One grouped work order therefore cannot point at ten complaints**, which is the whole shape of v1's cluster order. The representation instead is:

- `Complaint.cluster_id: Mapped[str | None]`, indexed — the **id of the cluster's lead complaint**, written on every member including the lead itself.
- The lead complaint carries the one work order, with the existing `WorkOrder.is_cluster=True` and `cluster_size=n` columns from Phase 0.
- "The work order for complaint X" is `X.work_order` when X is a lead, otherwise the work order of `X.cluster_id`. A helper `cluster_work_order(session, complaint)` in `clustering.py` (Task 4) expresses that once so no caller re-derives it.

Rejected: a `complaint_clusters` join table (a second source of truth for membership, and nothing else in the schema needs it); dropping the unique constraint (it exists to protect `uselist=False`); `WorkOrder.notes LIKE '%[CLUSTER]%'` (v1's approach, and the reason `is_cluster` exists).

- [ ] **Step 1: Test first**

```python
def test_cluster_members_point_at_their_lead(db_session):
    lead, member = _two_complaints(db_session)          # helper local to the test module
    lead.cluster_id = lead.id
    member.cluster_id = lead.id
    db_session.commit()
    members = db_session.query(Complaint).filter_by(cluster_id=lead.id).all()
    assert {c.id for c in members} == {lead.id, member.id}
    assert db_session.query(Complaint).filter_by(cluster_id=None).count() == 0
```

- [ ] **Step 2: Add the column** with a comment naming the constraint that forced the design:

```python
    # The lead complaint's id, on every member including the lead. A grouped
    # work order hangs off the lead, because work_orders.complaint_id is
    # unique and one row cannot reference ten complaints.
    cluster_id: Mapped[str | None] = mapped_column(String(36), index=True)
```

- [ ] **Step 3: Migration.** `cd backend && DATABASE_URL="sqlite:////tmp/civicai_mig.db" .venv/bin/python -m alembic upgrade head && DATABASE_URL="sqlite:////tmp/civicai_mig.db" .venv/bin/python -m alembic revision --autogenerate -m "add cluster_id to complaints" && rm /tmp/civicai_mig.db`. Confirm exactly one `add_column` inside `batch_alter_table` plus its `drop_column`, delete the `# ### commands auto generated` boilerplate, then `pytest tests/db -q` — the drift test must pass.

- [ ] **Step 4: Full suite** — expect **386 + 1 = 387**. Commit: `feat: record cluster membership on the complaint`.

---

### Task 4: Semantic clustering, as pure functions

**Files:**
- Create: `app/services/clustering.py` (the pure half only; the job is Task 5)
- Test: `tests/services/test_clustering.py`

**Interfaces:**
- `haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float`
- `cosine(u: np.ndarray, v: np.ndarray) -> float` — vectors from `Embedder.embed_documents` are already unit length, but the function normalises anyway and says why.
- `@dataclass(frozen=True) Candidate(id: str, text: str, coords: tuple[float, float], priority: int, created_at: datetime, category: str)`
- `@dataclass Cluster(lead: Candidate, members: list[Candidate])` with `size` and `ids`
- `cluster_candidates(candidates, *, embedder, radius_km, threshold, min_size) -> list[Cluster]`

The algorithm, and why:

1. Sort by `(-priority, created_at, id)`. Deterministic, and the most urgent report leads the cluster — it is the one whose category and district the grouped work order inherits.
2. Embed every candidate's text once, in one `embed_documents` call. One network round trip per tick, not one per pair.
3. Walk the sorted list; skip anything already claimed. For a lead, claim every unclaimed candidate within `radius_km` **and** at or above `threshold` cosine. Emit a `Cluster` only when `size >= min_size`; otherwise release the lead's claims — a pair is not a cluster, and its members must stay available to a later lead.
4. **Category is not part of the match.** That is the point of the rewrite: "pothole on MG Road" and "the road surface collapsed near MG Road" may be classified ROADS and CONSTRUCTION and are still one job for one crew. The cluster's category is the lead's, and the work order routes on it. A test asserts the mixed-category case groups, and a comment records that a cluster spanning categories routes to the lead's department on purpose.
5. **A candidate with no coordinates is never clustered.** v1 wrote `round(complaint.latitude or 0, 2)`, which put every coordinate-less complaint in one bucket at (0°, 0°) in the Gulf of Guinea. The caller filters them out and a test pins it.

```python
def test_two_reports_of_the_same_problem_group_even_across_categories():
    """v1 required identical category labels and identical rounded coordinates."""
    trench = _candidate("the contractor dug up MG Road and never filled it", (12.9716, 77.5946), category="CONSTRUCTION")
    hole = _candidate("huge hole in the road surface on MG Road", (12.9718, 77.5949), category="ROADS")
    caved = _candidate("MG Road has caved in near the junction", (12.9719, 77.5944), category="ROADS")
    clusters = cluster_candidates([trench, hole, caved], embedder=_semantic_embedder(), radius_km=0.5,
                                  threshold=0.8, min_size=3)
    assert len(clusters) == 1
    assert clusters[0].size == 3
    assert clusters[0].lead.category == clusters[0].members[0].category


def test_distance_beats_similarity():
    """Identical text 40 km apart is two problems, not one."""
    near = _candidate("pothole outside the school gate", (12.9716, 77.5946))
    far = _candidate("pothole outside the school gate", (13.3400, 77.1000))
    assert cluster_candidates([near, far, near], embedder=FakeEmbedder(), radius_km=0.5,
                              threshold=0.8, min_size=2) == [] or all(
        c.size == 2 for c in cluster_candidates([near, near, far], embedder=FakeEmbedder(),
                                                radius_km=0.5, threshold=0.8, min_size=2))


def test_a_pair_is_not_a_cluster_and_its_members_stay_available():
    ...  # min_size=3 with two similar and one far: no cluster, and no candidate claimed


def test_haversine_matches_a_known_distance():
    # Bangalore City Station to Bangalore Cantonment, ~4.0 km
    assert haversine_km((12.9767, 77.5713), (12.9989, 77.5905)) == pytest.approx(3.0, abs=1.0)
```

`FakeEmbedder` is content-hashed, so *only identical strings* are similar under it. Two tests above need near-duplicate-but-not-identical text to score highly, which the fake cannot do. Build a tiny `_semantic_embedder()` in the test module: a stub `Embedder` with a `model_tag` and a `embed_documents` that maps each text to a unit vector from a bag-of-words over a fixed small vocabulary (`{"road", "pothole", "hole", "trench", "mg", "school", …}`), so overlapping words really do produce a high cosine. Twenty lines, deterministic, offline, and it makes the threshold meaningful in a test instead of vacuous. Say so in its docstring, and note that whether 0.82 is the right threshold on real text is a Phase 3 eval question.

- [ ] **Step 1: Write those tests.** **Step 2: Watch them fail** (`ModuleNotFoundError`). **Step 3: Implement.** **Step 4:** expect **387 + 8 = 395**. **Step 5: Commit** — `feat: cluster complaints by meaning within a radius, not by a rounded coordinate`.

---

### Task 5: The hourly cluster job and its grounded work order

**Files:**
- Modify: `app/services/clustering.py` (the DB half), `app/ai/rag/corpus/rate_card.md`, `app/ai/prompts/templates.py`, `__init__.py`, `app/ai/llm.py`, `app/config.py`, `.env.example`
- Test: `tests/services/test_clustering.py` (append), `tests/ai/rag/test_corpus.py` (append), `tests/ai/test_prompts.py` (append)

**Interfaces:**
- `CLUSTERABLE_STATUSES = ("processed", "assigned")` — derived from `_status_for` in `runner.py`: `submitted` has no category yet, `rejected`/`failed` have no work to do, `resolved` is done. Confirm the vocabulary against that function before writing the filter.
- `open_candidates(session, *, tenant_id) -> list[Candidate]` — status in `CLUSTERABLE_STATUSES`, `cluster_id is None`, `category is not None`, both coordinates present, and no completed work order.
- `cluster_work_order(session, complaint) -> WorkOrder | None` — the helper Task 3 promised.
- `detect_clusters(*, session_factory, embedder=None, cost_chain=None, retriever=None, now=None) -> ClusterTick` where `ClusterTick(clusters: int = 0, complaints: int = 0)`. **Per tenant**, never across (the SLA monitor's tenant-blindness is on the Phase 2b carry-forward list; do not add a second instance of it).
- The grouped work order: written against the lead, `is_cluster=True`, `cluster_size=n`, `sla_hours` from the *highest* risk band among members (`sla_hours_for` from Task 2), `estimated_cost` and `cost_basis` from a new `WORK_ORDER_CLUSTER_V1` chain on `Task.WORK_ORDER`, and `contractor_id` from `score_contractor` over the lead's category. Members get `cluster_id` and a `decision`-style note; a member that already had its own non-completed work order keeps it (do not delete work already dispatched — record the cluster and let the officer reconcile), and a test pins that.
- Idempotency: a second call in the same hour finds `cluster_id` set on all of them and returns `ClusterTick()`.

**The bulk discount must come from the document.** v1 priced a cluster at `base × count × 0.7` in Python. There is no bulk rule anywhere in `corpus/rate_card.md` today (sections: Purpose, Unit rates by item, Labour and equipment rates, Notes on use), so this task adds one:

```markdown
## Grouped work at multiple sites

When one crew fixes several nearby sites in a single mobilisation, material
quantities are summed at the unit rates above, but labour and equipment are
charged once for the mobilisation plus a reduced per-site allowance: the
second and subsequent sites are billed at 70% of their standalone labour and
equipment cost. A grouped estimate must state the number of sites and show
the mobilisation saving as a separate line so it can be audited against the
contractor's invoice.
```

`tests/ai/rag/test_corpus.py` gains `test_the_rate_card_states_a_rule_for_grouped_work` asserting the section exists and mentions a percentage — otherwise the cluster prompt asks the model to cite a rule that is not there, and it will invent one. `WORK_ORDER_CLUSTER_V1` takes `{category, risk_level, site_count, descriptions, evidence}` and is registered as `("work_order_cluster", "v1")`.

Settings (with `.env.example` entries, or `test_config.py::test_every_settings_field_is_documented_in_env_example` fails):

```python
    cluster_radius_km: float = 0.5
    cluster_similarity_threshold: float = 0.82
    cluster_min_size: int = 3
```

Key tests:

```python
async def test_three_nearby_reports_become_one_grouped_work_order(db_session):
    ...
    tick = detect_clusters(session_factory=lambda: db_session, embedder=_semantic_embedder(),
                           cost_chain=returns(CostEstimate(estimated_cost=21000.0,
                                                           cost_basis="3 sites, mobilisation once [1]",
                                                           materials="hot mix")),
                           retriever=FakeRetriever([_hit("second and subsequent sites at 70%", "rate_card.md",
                                                         ["Municipal Rate Card", "Grouped work at multiple sites"])]))
    assert (tick.clusters, tick.complaints) == (1, 3)
    order = db_session.query(WorkOrder).filter_by(is_cluster=True).one()
    assert order.cluster_size == 3
    assert "70%" in order.cost_basis or "mobilisation" in order.cost_basis
    assert db_session.query(Complaint).filter_by(cluster_id=order.complaint_id).count() == 3


def test_a_second_tick_clusters_nothing(db_session):
    ...  # same fixture, call twice, second returns ClusterTick()


def test_clusters_never_span_tenants(db_session):
    ...  # identical text, identical coordinates, two tenants, min_size=2 -> no cluster


def test_the_grouped_window_is_the_most_urgent_members(db_session):
    ...  # a critical member among mediums gives the cluster the critical window


def test_a_failed_cost_chain_still_produces_the_cluster(db_session):
    """Grounding is a soft dependency here too: the crew still needs the job."""
    ...  # raises(RuntimeError) as cost_chain -> work order exists, cost_basis says estimate unavailable
```

- [ ] Steps 1–5 as before. Expect **395 + 9 = 404**. Commit: `feat: group nearby complaints into one grounded cluster work order`.

---

### Task 6: The daily briefing that has never once worked

**Files:**
- Create: `app/services/briefing.py`
- Modify: `app/ai/schemas.py`, `app/ai/prompts/templates.py`, `__init__.py`, `app/ai/llm.py` (`Task.BRIEFING`)
- Test: `tests/services/test_briefing.py`, `tests/ai/test_prompts.py` (append)

v1's `briefing.py` called a method that does not exist, so every briefing ever produced was the hardcoded template and nothing recorded that. `DailyBriefing.is_fallback` exists in the schema for exactly this. The test that matters most in this task is the one asserting the flag is `False` on the happy path — a green suite that never checks it would reproduce v1's bug exactly.

**Interfaces:**
- `@dataclass BriefingStats(new_complaints, resolved_today, sla_at_risk, escalations_today, clusters_detected)`
- `gather_stats(session, *, tenant_id, day: date) -> BriefingStats` — pure counting, no model. `sla_at_risk` reuses `elapsed_fraction` and `WARNING_AT` from `services/sla.py` rather than re-deriving the band.
- `BriefingNarrative(BaseModel)`: `summary: str`, `priorities: list[str]` (≤3), `citations: list[str]`.
- `generate_briefing(*, session_factory, tenant_id=None, day=None, chain=None, retriever=None) -> DailyBriefing` — retrieves `{"doc_type": "sla_policy"}`, invokes the chain, writes one row. On any chain failure: template text from the stats, `is_fallback=True`, `logger.warning`. One row per `(tenant_id, day)`: a second call updates that row instead of inserting.
- `fallback_narrative(stats) -> str` — the template, kept in one place and tested for the numbers it must contain.

```python
def test_a_real_briefing_is_not_marked_as_a_fallback(db_session):
    """v1 served template text for its entire life and recorded nothing. The
    flag is the record; this assertion is the reason it exists."""
    seeded = seed_database(db_session)
    _complaints_for_a_day(db_session, seeded["tenant_id"])
    row = generate_briefing(session_factory=lambda: db_session, tenant_id=seeded["tenant_id"],
                            chain=returns(BriefingNarrative(summary="Four new reports, two resolved.",
                                                            priorities=["Clear the MG Road cluster"],
                                                            citations=["sla_policy.md › Priority bands"])),
                            retriever=FakeRetriever([_hit("High risk: 24 hour response.", "sla_policy.md",
                                                          ["SLA Policy", "Priority bands"])]))
    assert row.is_fallback is False
    assert "MG Road" in row.narrative
    assert row.new_complaints == 4


def test_a_broken_chain_falls_back_visibly(db_session, caplog):
    with caplog.at_level("WARNING"):
        row = generate_briefing(session_factory=lambda: db_session, chain=raises(AttributeError("_has_api_key")),
                                retriever=FakeRetriever())
    assert row.is_fallback is True
    assert str(row.new_complaints) in row.narrative
    assert "briefing" in caplog.text


def test_one_row_per_tenant_per_day(db_session):
    ...  # two calls -> one row, second narrative wins


def test_stats_count_only_the_requested_day_and_tenant(db_session):
    ...  # yesterday's and another tenant's complaints excluded
```

`BRIEFING_V1` takes `{date, stats_table, at_risk_list, cluster_list, evidence}` and asks for a short officer-facing narrative citing `[n]`; the system turn states plainly that the numbers are given and must not be recomputed or embellished. Register `("briefing", "v1")`, `LATEST["briefing"] = "v1"`, `Task.BRIEFING: settings.gemini_model_strong` (it is prose a human reads — the tiering rule in `llm.py` already says so for `NARRATE`; use `Task.NARRATE` if you prefer not to add a task, but then say why in the docstring).

- [ ] Steps 1–5. Expect **404 + 7 = 411**. Commit: `feat: generate the daily briefing from the day's numbers and the SLA policy`.

---

### Task 7: The officer email draft

**Files:**
- Create: `app/services/email_draft.py`
- Modify: `app/ai/schemas.py`, prompts, `app/ai/llm.py` (`Task.EMAIL_DRAFT`)
- Test: `tests/services/test_email_draft.py`, `tests/ai/test_prompts.py` (append)

**Scope boundary, stated so nobody looks for it:** this task builds the chain and the service that writes `Complaint.email_draft`. It adds **no HTTP endpoint**, because there is no officer authentication in the codebase yet — `app/api/` is citizen-only and the JWT layer belongs to the officer work in Phase 4/5. The approval flow (`email_approved`, an officer edit, the send) goes there too, and this plan's "Done When" says so.

**Interfaces:**
- `EmailDraft(BaseModel)`: `subject: str`, `body: str`, `citations: list[str]`
- `draft_department_email(*, complaint_id, session_factory, chain=None, retriever=None) -> EmailDraft` — retrieves `{"doc_type": "sop", "category": <complaint category>}`, invokes the chain, writes `complaint.email_draft` (the rendered `subject`/`body`) and leaves `email_approved=False`. Raises `ValueError` for an unknown complaint; returns the existing draft untouched when `email_approved` is already `True` (never overwrite what an officer approved) — and a test pins that.
- `EMAIL_DRAFT_V1` takes `{department, category, tracking_id, description, risk_level, sla_hours, evidence}`, fences the citizen text in `<report>`, and asks for a formal municipal email citing the SOP clause that makes this the department's responsibility.

```python
def test_the_draft_cites_the_department_sop(db_session):
    complaint = _classified_complaint(db_session, category="ROADS")
    seen = {}
    def capture(payload):
        seen.update(payload)
        return EmailDraft(subject="Pothole at MG Road — action required",
                          body="Under the Roads SOP [1] this is Public Works' responsibility…",
                          citations=["sop_roads.md › Roads SOP › Ownership"])
    draft = draft_department_email(complaint_id=complaint.id, session_factory=lambda: db_session,
                                  chain=RunnableLambda(capture),
                                  retriever=FakeRetriever([_hit("Public Works owns road surface defects.",
                                                                "sop_roads.md", ["Roads SOP", "Ownership"])]))
    assert seen["department"] == "Public Works Department"
    assert "[1] sop_roads.md › Roads SOP › Ownership" in seen["evidence"]
    db_session.expire_all()
    assert "Public Works" in db_session.query(Complaint).one().email_draft
    assert db_session.query(Complaint).one().email_approved is False


def test_an_approved_draft_is_never_overwritten(db_session):
    ...  # email_approved=True -> chain not invoked, stored text unchanged


def test_a_missing_sop_still_produces_a_draft(db_session):
    ...  # retriever raising -> draft written, evidence block says nothing was retrieved
```

- [ ] Steps 1–5. Expect **411 + 6 = 417**. Commit: `feat: draft the department email from the SOP with a structured chain`.

---

### Task 8: Register the jobs

**Files:**
- Modify: `app/services/scheduler.py`, `app/config.py`, `.env.example`
- Test: `tests/services/test_scheduler.py` (extend)

Three jobs join `sla_monitor`:

| id | trigger | body |
|---|---|---|
| `cluster_detection` | `interval`, 60 min | `detect_clusters(session_factory=…)` |
| `daily_briefing` | `cron`, `hour=settings.briefing_hour`, `minute=0` | `generate_briefing(session_factory=…)` per tenant |
| `cases_refresh` | `cron`, `hour=settings.briefing_hour - 1` | `ingest_cases(...)` — closes the Phase 2b carry-forward item that nothing refreshes the cases index |

Each follows the `sla_job` shape exactly: `asyncio.to_thread`, `max_instances=1`, `coalesce=True`, its own `try/except` logging at `exception` so one failing job never stops the scheduler. `cases_refresh` carries a comment that `FaissStore.save` rewrites the index directory, so this job must be the only writer — which is true while the deployment runs one process, and is the second reason `build_scheduler`'s single-process caveat matters.

Settings: `briefing_hour: int = 8`, `cluster_detection_enabled: bool = True`, `briefing_enabled: bool = True`, `cases_refresh_enabled: bool = True` — each with a `.env.example` line. `background_jobs_enabled` remains the master switch.

```python
def test_every_expected_job_is_registered():
    scheduler = build_scheduler(session_factory=lambda: None)
    assert {j.id for j in scheduler.get_jobs()} == {"sla_monitor", "cluster_detection", "daily_briefing", "cases_refresh"}


def test_a_disabled_job_is_not_registered(monkeypatch):
    monkeypatch.setattr(settings, "briefing_enabled", False)
    assert build_scheduler(session_factory=lambda: None).get_job("daily_briefing") is None


def test_the_briefing_runs_at_the_configured_hour():
    job = build_scheduler(session_factory=lambda: None).get_job("daily_briefing")
    assert str(job.trigger.fields[job.trigger.FIELD_NAMES.index("hour")]) == str(settings.briefing_hour)


def test_one_failing_job_does_not_stop_the_others(caplog):
    ...  # call the job coroutine directly with a session_factory that raises; assert it logs and returns
```

- [ ] Steps 1–5. Expect **417 + 4 = 421**. Commit: `feat: run cluster detection, the daily briefing and the cases refresh on a schedule`.

---

## Phase 2c Done When

- [ ] `cd backend && .venv/bin/python -m pytest -q` passes — **421 tests**, no network, no key, `git status --porcelain` empty afterwards
- [ ] `grep -rn "SLA_HOURS" backend/app` finds only `app/services/tenancy.py`; no lookup dict of municipal values remains in `app/ai/graph/nodes/`
- [ ] Three reports of the same problem 200 m apart with *different* categories become one work order with `is_cluster=True`, `cluster_size=3`, and a `cost_basis` citing the rate card's grouped-work section
- [ ] A complaint with no coordinates is never clustered; a cluster never spans two tenants
- [ ] `generate_briefing` with a working chain writes `is_fallback=False`; with a raising chain it writes `is_fallback=True`, logs a warning, and the narrative still carries the day's numbers
- [ ] Running every job twice in a row changes nothing the second time
- [ ] `assess_risk` retrieves precedent only from the complaint's own tenant, and retrieves none at all when the complaint has no tenant
- [ ] `cache_for("classify", "v1") is not cache_for("classify", "v2")`
- [ ] The API boots with `BACKGROUND_JOBS_ENABLED=false` and registers no jobs; with it true, `scheduler.get_jobs()` names all four

**Deliberately not in this phase:** the officer HTTP surface (draft/approve/send endpoints, JWT auth) — Phase 4/5; `WorkOrder.actual_cost` has no writer until a completion path exists, so case records still fall back to the estimate (Phase 2b carry-forward, closed there); `retrieved_chunks` still stores no `DocumentChunk.id` (Phase 2a carry-forward, still open, and cheapest to do alongside the Phase 3 eval schema).

**Next:** Phase 3 — the golden set, metrics, judges, Ragas, and the three-way baseline comparison over the v1/v2 prompt versions this phase and Phase 2b kept registered. Read Task 1's cache note first: an eval sweep must build its own caches, never `cache_for`.

---

## Carried forward from Phase 2c (recorded 2026-09-27)

Phase 2c landed in eight commits (22919ad..521af37), 439 tests, no network in the
suite, `git status --porcelain` empty. The plan projected 421; the extra came from
edge cases the tasks turned out to need (a nonsense SLA config, a lead that already
has a work order, contractor zone scoring, per-job switches).

**Review status, again uneven.** Every task was implemented against its own tests
in one sitting, with no independent review pass. The items below come from reading
the finished code. The three Phase 2b seams this phase promised to close are
closed; two Phase 2b items remain open and are restated at the end.

**The functional gap worth fixing first**
- **A cluster never grows.** `open_candidates` filters on `cluster_id IS NULL`, so
  once three reports are grouped, the fourth report of the same pothole is not a
  candidate for that cluster — it waits for two *more* reports to form a second
  cluster of its own, at the same place, with a second work order and a second
  crew. v1 re-bucketed everything every hour and so did not have this problem (it
  had worse ones). The fix is a join path: consider an existing cluster's lead as
  a possible match for an unclustered candidate, and on a match set `cluster_id`,
  bump `cluster_size`, and re-price. It needs a decision about whether re-pricing
  a dispatched work order is allowed, which is why it is not a silent addition.

**Clustering — now measured (Phase 3's clustering eval, 2026-09-28)**
- **The threshold is validated.** On `gemini-embedding-001`, pair-wise precision
  and recall over the duplicate slice are both 1.00 across 0.80–0.90, collapse to
  0.00 recall at 0.95, and fall to 0.30 precision at 0.50–0.70. The configured
  0.82 sits mid-band with margin either side. That item is closed.
- **Fixed (2026-10-04): the greedy lead could steal a tighter group's members.**
  Measured before and after on real embeddings, at the threshold where it bit:

  | threshold 0.75 | precision | recall |
  |---|---|---|
  | first-acceptable lead | 0.11 | 0.17 |
  | best-first by cohesion | **0.67** | **1.00** |

  Recall is now 1.00 across 0.60-0.90 instead of collapsing at 0.75, so the
  detector is monotonic in the threshold: lowering it costs precision and never
  recall, which is the shape it should always have had. Selection scores the
  candidate cluster around every unclaimed seed by mean pairwise similarity and
  emits the most cohesive; urgency now only decides who leads a chosen group. The
  original failure is a deterministic test in `test_clustering.py`.

  The defect as recorded at the time: At a marginal threshold an unrelated but higher-priority complaint
  becomes the lead, matches part of a real group, and emits a cluster — and
  because `claimed` then makes those members unavailable, the real group can no
  longer form. Measured at threshold 0.75: `amb-fw-10` (priority 70) took `dup-1c`
  and left `dup-1a`/`dup-1b` unclustered, dropping recall to 0.17. The detector is
  therefore **non-monotonic in the threshold** and sensitive to priority ordering.
  At the configured 0.82 it does not bite, which is luck rather than design.
  The fix is to stop letting the first acceptable lead win: score candidate
  clusters (mean intra-cluster similarity, say) and emit the best, or require a
  lead to be mutually nearest with its members. Either needs a decision about
  cost, since both mean comparing more pairs.

**Clustering**
- Unclustered complaints are re-embedded every hour, per tenant, forever. At a few
  hundred open complaints that is one cheap batch; at a few thousand it is a real
  bill for no new information. Store the embedding (or cache it by complaint id) —
  Phase 3's eval sweeps want the same thing.
- Pair comparison is O(n²) per tenant. Fine at hundreds; if it stops being fine,
  the fix is to bucket by a coarse geohash first and compare within buckets, which
  is v1's grid used as a *pre-filter* rather than as the answer.
- `cluster_work_order()` is written, tested and **called by nothing**. It is the
  helper any "show me this complaint's work order" path needs, and that path is
  Phase 5. Either wire it when the officer screens land or delete it.
- A grouped work order does not touch its members' `status`, and no member's
  citizen is told their report was merged into one job. The `Escalation`-style
  audit row does not exist for clustering either: the only record is
  `cluster_id` plus the work order's `notes` string.
- `_worst_risk` re-queries the member complaints that `open_candidates` already
  read, because `Candidate` carries `district` but not `risk_level`. Thread it the
  way `district` was.
- Contractor selection is `max(score_contractor(...))` over every contractor in
  the tenant, so specialisation adds weight but does not gate — the same shape as
  the SLA monitor's reassignment, noted on Phase 2b's list. One scoring fix covers
  both.
- `cluster_similarity_threshold = 0.82` has never been measured against real
  embeddings. The tests use a bag-of-words fake specifically so the threshold is
  not vacuous, and say so; what the right number is on real prose is a Phase 3
  eval question.

**Briefing**
- **`resolved_today` counts `Complaint.updated_at`**, which carries
  `onupdate=utcnow`. Any edit to a resolved complaint moves it into a later day's
  count, and a complaint resolved yesterday but touched today is counted today.
  There is no `resolved_at` column; adding one is the honest fix and it also gives
  case records a real resolution timestamp.
- **The day is UTC midnight to UTC midnight.** For a Bengaluru municipality,
  `BRIEFING_HOUR=8` reports 05:30 IST yesterday to 05:30 IST today. `Tenant` has
  no timezone, so this cannot be fixed without modelling one.
- `BriefingNarrative.citations` is **dropped**: only `summary` and `priorities` are
  rendered into `narrative`. The model is asked to cite `[n]` and the citation
  strings are then thrown away, so an officer sees `[1]` with no key. Either
  render them or stop asking for them.
- `sla_at_risk` is "at risk *now*", not "at risk during that day", so a briefing
  generated for a past date reports today's exposure. Right for the 08:00 job,
  wrong for a backfill.
- `generate_briefing` commits once after looping every tenant, so a database error
  on the fifth tenant discards the four rows already written. Per-tenant commits
  would match `detect_clusters`.

**Email draft**
- The approved-draft early return rebuilds an `EmailDraft` with `subject` as the
  first line and `body` as the *whole* stored text, so the returned body repeats
  the subject. Callers that render `subject` and `body` separately will show it
  twice. The underlying cause is that the draft is stored as one `Text` column
  with the subject concatenated; a `email_subject` column, or storing JSON, fixes
  both.
- Nothing calls this service either — by design, stated in the plan: `app/api/` is
  citizen-only and no officer authentication exists. Draft/approve/send is Phase
  4/5 work.

**Still open from Phase 2b**
- Nothing writes `WorkOrder.actual_cost`, so case records still teach the
  estimate rather than the outcome. A completion path is the prerequisite.
- `retrieved_chunks` stores the derived `chunk_id` but not `DocumentChunk.id` or
  the header path, so there is no durable join from a stored citation back to the
  indexed row. Cheapest to do alongside Phase 3's eval schema work, which touches
  the same tables.
