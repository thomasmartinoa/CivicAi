# CivicAI v2 — Design Spec

**Date:** 2026-09-02
**Branch:** `dev_1`
**Status:** Approved for planning

---

## 1. Purpose

CivicAI v1 is an AI complaint-resolution system whose "multi-agent pipeline" is a `for` loop over seven
objects that mutate a shared dataclass. It works, but it has no branching, no memory, no resumability,
no retrieval, no tests, and no way to measure whether the AI is any good.

v2 rebuilds the AI core on **LangChain + LangGraph**, grounds its decisions in **retrieval over a real
municipal knowledge corpus**, and puts a **measurable evaluation harness** around the whole thing.

Two goals, weighted equally:

1. **A better system.** Decisions become grounded and auditable instead of hardcoded and opaque.
2. **A teaching artifact.** Every design choice is documented with its alternatives, so the author can
   defend the system in a technical interview.

Non-goal: real government API integration. Contractor and officer data stay mocked, as in v1.

---

## 2. Decisions taken

| Decision | Choice | Rationale |
|---|---|---|
| Rewrite strategy | Greenfield backend; v1 deleted | Clean architecture matters more than preserving working-but-tangled code. v1 survives in git history and in `docs/01-legacy-system-explained.md`. Its ~30-line keyword classifier is the one thing ported forward, into `evals/baseline.py`, so every metric has a before/after column. |
| Orchestration | LangGraph `StateGraph` | Typed state, conditional edges, durable checkpoints, native tracing. |
| Agent architecture | Hybrid (deterministic spine + scoped agentic loops) | SLA decisions must be reproducible and auditable; LLM-driven control flow is reserved for open-ended retrieval and conversation. |
| Relational store | SQLite | Zero-setup local dev. Postgres remains a config change. |
| Vector store | FAISS (`IndexFlatIP`) | No torch dependency, cp314 wheels available, corpus small enough that post-filtering is acceptable. |
| Embeddings | Gemini `gemini-embedding-001` @ 768d, Ollama `nomic-embed-text` fallback | Free tier; no 2 GB local model download. |
| LLM | Gemini `2.5-flash-lite` primary, Ollama local fallback | Free tier; fallback keeps the system alive under rate limits. |
| Tracing | LangSmith | Native LangGraph integration; industry-standard artifact for a portfolio. |
| Human-in-the-loop / guardrails | Deferred to a possible Phase 7 | Explicitly descoped by the author. The Phase 3 golden dataset still includes injection cases so the need can be evidenced. |

---

## 3. Architecture

### 3.1 Module layout

```
backend/app/
  main.py            FastAPI app, lifespan, scheduler
  config.py          pydantic-settings
  db/                session.py, models/
  api/               routers — HTTP only, no business logic
  schemas/           request/response DTOs
  services/          non-AI: media, email, otp, geocode, websocket
  ai/                ALL AI. Importable with no web server running.
    llm.py           model factory, fallbacks, tiering, rate limiting
    cache.py         semantic cache
    schemas.py       Pydantic OUTPUT schemas
    prompts/         versioned templates (classify_v1, classify_v2, ...)
    graph/
      state.py       ComplaintState + reducers
      nodes/         one module per node
      subgraphs/     media.py, investigate.py
      build.py       assemble + compile
      runner.py      invoke/stream, persist results
    rag/
      corpus/        authored markdown knowledge base
      ingest.py      load -> chunk -> embed -> index
      store.py       FAISS behind a VectorStore protocol
      retrievers.py  dense, BM25, hybrid (RRF), reranker
    agents/          officer_chat.py (ReAct)
    tools/           @tool functions
    observability.py LangSmith wiring, run metadata
  evals/
    datasets/        golden_complaints.jsonl
    metrics.py  judges.py  baseline.py  run.py
```

**Dependency rules** (enforced by an import-lint test):

- `api/` must not import `ai/graph/` directly — it goes through `ai/graph/runner.py`.
- `ai/` must not import `api/`.

The point is that the entire AI system runs from a script or a pytest with no HTTP layer.

### 3.2 Graph topology

```
START
  |
  v
intake ---- Send() fan-out ----> [ analyze_media x N ]
  |                                      |
  |<------------ merge -----------------+
  v
validate --- invalid ---> reject ---> END
  |
  v
classify                      (structured output + confidence)
  |
  +-- confidence < 0.7 or category unknown --> investigate (subgraph, loops <= 3)
  |                                                  |
  v<-------------------------------------------------+
assess_risk                   (RAG: similar past cases + real outcomes)
  |
  v
route                         (RAG: department SOPs, cited)
  |
  v
work_order                    (RAG: rate card + past actual costs)
  |
  v
notify --> END
```

Compiled with `AsyncSqliteSaver` over `checkpoints.db`, `thread_id = complaint_id`.
`RetryPolicy(max_attempts=3)` on every LLM node.
Runs stream via `graph.astream(stream_mode="updates")` into the existing WebSocket.

### 3.3 State

```python
class ComplaintState(TypedDict):
    # immutable input
    complaint_id: str
    tracking_id: str
    tenant_id: str | None
    raw_description: str
    media: list[MediaRef]
    coords: Coords | None

    # written in parallel -> require reducers
    media_insights: Annotated[list[MediaInsight], operator.add]
    evidence:       Annotated[list[RetrievedChunk], operator.add]
    decision_log:   Annotated[list[NodeDecision], operator.add]
    errors:         Annotated[list[str], operator.add]

    # enriched
    description: str
    location: LocationInfo | None

    # AI outputs — Pydantic models, never dicts
    validation:     ValidationResult | None
    classification: ClassificationResult | None
    risk:           RiskAssessment | None
    routing:        RoutingDecision | None
    work_order:     WorkOrderDraft | None

    # control
    investigate_turns: int
    terminal_reason: str | None
```

### 3.4 Node contract

Every node is a function `(state, config) -> dict` returning a **partial** state update. Nodes never
mutate state and never write to the database. Dependencies (DB session factory, vector store, model
registry) are injected through `config["configurable"]`, which is what makes nodes unit-testable
against fakes.

Persistence happens in `runner.py` after the graph completes or checkpoints, not inside nodes.

### 3.5 Background workflows

Three v1 responsibilities run on a schedule rather than per complaint. They are not part of the
complaint graph and must not be lost in the rewrite.

| Job | v2 treatment | Cadence |
|---|---|---|
| **SLA monitor** | Pure deterministic Python in `services/sla.py` — no LLM. Warns at 50% and 75% of the SLA window, escalates and reassigns the contractor on breach. Ported from v1 logic with tests. | every 5 min |
| **Cluster detection** | **Rewritten as semantic clustering.** v1 bucketed complaints by rounded lat/lng, so "pothole on MG Road" and "road caved in near MG Road" only grouped if their coordinates rounded identically. v2 embeds open complaints and clusters by cosine similarity within a geographic radius, then generates one grouped work order. | hourly |
| **Daily briefing** | A small LangGraph chain grounded in the day's statistics plus retrieved SLA policy, producing a narrative for the officer with citations. | 08:00 daily |

Two v1 bugs are fixed in passing, both documented in `docs/01-legacy-system-explained.md` as worked
examples of what goes wrong without tests:

- `briefing.py` calls `llm_service._has_api_key()`, which does not exist — it is a module-level
  function taking a provider argument. The daily briefing therefore raises on every run and has
  *always* silently served fallback text.
- The same file imports `google.generativeai` (the superseded SDK) while the rest of the codebase uses
  `google.genai`.

### 3.6 Retained v1 features

Carried into v2 unchanged in behaviour, rebuilt on the new structure: citizen OTP email verification,
WebSocket status updates, complaint rating with contractor rolling-average updates, citizen
re-verification and auto-reopen, multi-tenancy, and the **officer email-draft flow** (LLM-drafted
department email, officer edits and approves). The email draft becomes a structured-output chain with
retrieval of the relevant department SOP, replacing v1's free-text prompt.

---

---

## 4. RAG subsystem

### 4.1 Corpora

Two indexes with deliberately different characteristics.

**`policy` — static, authored** (`ai/rag/corpus/*.md`):

| Corpus | Consumed by |
|---|---|
| 12 department SOPs (ownership, response norms, materials) | `route` |
| SLA policy handbook (priority bands, escalation ladder) | `assess_risk`, `work_order` |
| Category taxonomy guide (ROADS vs CONSTRUCTION edge cases) | `investigate` |
| Municipal rate card (material and labour rates) | `work_order` |

**`cases` — dynamic**: every resolved complaint is indexed with its actual resolution time, actual cost
and contractor. `assess_risk` reasons from real outcomes instead of constants.

Chunking differs by corpus and this is intentional teaching material: policy documents use
`MarkdownHeaderTextSplitter` then a recursive split (~500 tokens, 80 overlap) with headers retained as
metadata; case records are short and are stored as one chunk each with no splitting.

### 4.2 Retrieval

```
query -> embed -> FAISS dense (cosine)  --+
      -> BM25 sparse (rank_bm25)  --------+--> RRF fusion (k=60)
                                              -> fetch_k=50
                                              -> metadata post-filter
                                              -> LLM reranker (flag-gated) -> top 5
                                              -> state["evidence"] + citations
```

**Documented tradeoffs:**

1. FAISS has no metadata filtering, so we over-fetch and filter in Python. Acceptable below ~10k chunks.
   Recorded in `docs/adr/0002-faiss-over-pgvector.md`.
2. Reranking uses an LLM rather than a cross-encoder, to avoid a torch dependency. It is flag-gated and
   **measured in the eval suite**; if it does not beat RRF alone on context precision it gets disabled,
   and that negative result is itself documented.

**Embedding dimension safety:** both providers are pinned to 768 dimensions, and the embedding model
name is stamped into index metadata. Querying an index built by a different model raises rather than
returning silent garbage.

Every RAG-consuming node emits citations, so every AI decision can show its sources in the UI.

---

## 5. LLM layer (`ai/llm.py`)

| Concern | Mechanism |
|---|---|
| Structured output | `.with_structured_output(Schema)` — removes v1's regex JSON rescue entirely |
| Provider failover | `gemini.with_fallbacks([ollama_local])` |
| Model tiering | flash-lite for validate/classify; stronger model for risk and briefing; configured per task |
| Semantic cache | Embed prompt; cosine > 0.95 against cache returns the stored completion. Reuses the FAISS stack. |
| Rate limiting | `InMemoryRateLimiter` — required to run a 100-item eval sweep on a free tier |
| Prompt versioning | Templates named `classify_v1`, `classify_v2`; eval harness A/B tests them |

---

## 6. Data model

Fresh Alembic baseline. Ported and cleaned from v1: `tenants`, `users`, `departments`, `contractors`,
`complaints`, `complaint_media`, `work_orders`, `escalations`, `notifications`, `daily_briefings`.

New AI tables:

| Table | Contents | Powers |
|---|---|---|
| `agent_runs` | thread_id, status, duration, tokens, est. cost, LangSmith URL | trace viewer, cost metrics |
| `agent_steps` | per-node sequence, timing, status, I/O summary, error | step timeline UI |
| `retrieved_chunks` | source, score, snippet, per node | "why did it decide that?" |
| `documents`, `document_chunks` | corpus registry and index status | knowledge-base admin |
| `eval_runs`, `eval_results` | metric, value, git sha, dataset hash | eval dashboard, regression tracking |

`complaints` gains `graph_thread_id`, `pipeline_version`, `evidence` (JSON citations).

Trace data is persisted locally in addition to LangSmith because the in-app viewer must work offline
and without an account, and because `agent_steps` is what the React screen renders.

Graph checkpoints live in a separate `checkpoints.db` so LangGraph's schema never collides with
application migrations.

---

## 7. Evaluation and observability

### 7.1 Observability

- LangSmith via `LANGCHAIN_TRACING_V2`; LangGraph traces natively.
- `@traceable` on non-LangChain code (FAISS retrieval, cache lookups) to close trace blind spots.
- Run metadata (`complaint_id`, `category`, `pipeline_version`, `prompt_version`) on every run so
  LangSmith is filterable.
- A callback handler mirrors step data into `agent_runs` / `agent_steps`.

### 7.2 Three layers of evaluation

**Layer 1 — deterministic tests (pytest, no API calls).** Nodes driven by `GenericFakeChatModel`;
reducer merge behaviour; graph topology; conditional-edge logic; retrieval ranking against a fixed
20-chunk corpus. Runs in CI.

**Layer 2 — golden dataset**, ~100 labelled complaints including non-infrastructure junk,
ROADS-vs-CONSTRUCTION ambiguity, and prompt-injection attempts in complaint text.

Reported for three configurations — naive keyword baseline (ported from v1), LLM without RAG, and full
v2:

- classification accuracy and macro-F1, plus per-category confusion matrix
- department routing accuracy
- risk band accuracy and priority-score MAE
- invalid-complaint precision/recall
- p95 latency, tokens, estimated cost per complaint

The middle column exists specifically to test whether RAG earned its place rather than assuming it did.

**Layer 3 — generative quality.** Ragas (`context_precision`, `context_recall`, `faithfulness`) over
retrieval; rubric judges for officer briefings and routing justifications. **Judge validation:** 20
hand-labelled items measure agreement between the LLM judge and the author, so judge scores are
reported with known bounds rather than taken on faith.

### 7.3 Regression gate

`python -m app.evals.run --suite core` exits nonzero if macro-F1 drops more than 2 points against the
stored baseline. Dataset is versioned in git and hashed per run. CI runs Layer 1 only (no API key);
Layers 2 and 3 run locally.

Reports are written to `docs/eval-reports/YYYY-MM-DD.md` and to `eval_runs` / `eval_results`.

---

## 8. Frontend additions

Existing React 18 + TS + Vite + Tailwind + React Query stack. Six new screens:

1. **Live pipeline view** — nodes light up over WebSocket as `astream` emits updates, replacing the
   current dead "submitted" state.
2. **Agent trace viewer** — per-node timeline with duration, tokens, status, expandable I/O, link to
   the LangSmith trace.
3. **Evidence panel** — citations behind each decision with source document and relevance score.
4. **Officer chat** — SSE-streamed ReAct agent that surfaces tool calls as they happen.
5. **Knowledge base admin** — corpus documents, chunk counts, reindex trigger.
6. **Eval dashboard** — metric trend across runs, comparison table, confusion-matrix heatmap.

---

## 9. Documentation deliverables

Written as each phase lands, for an intermediate Python programmer. Each doc follows the same shape:
explain the concept, show the actual code from this repo, explain why it is built that way and what was
rejected.

```
docs/
  00-README.md                     how to read these
  01-legacy-system-explained.md    how v1 worked (written before deletion)
  02-architecture-overview.md      v2 diagrams and request lifecycle
  03-langchain-fundamentals.md     LCEL, structured output, tools, callbacks
  04-langgraph-deep-dive.md        state, reducers, edges, Send, subgraphs, checkpoints
  05-rag-explained.md              chunk, embed, index, retrieve, ground
  06-llm-layer.md                  providers, fallbacks, caching, tiering
  07-evaluation-and-observability.md
  08-code-walkthrough.md           file by file: what and why
  09-interview-prep.md             Q&A, tradeoffs, "why not X"
  10-resume-lines.md               bullets plus the numbers behind them
  adr/                             one file per real decision
  eval-reports/
```

---

## 10. Phase plan

| Phase | Deliverable | Docs |
|---|---|---|
| **0** | Legacy explainer written; v1 deleted; new backend skeleton, config, models, baseline migration; app boots | 01 |
| **1** | Graph core: state, nodes, media subgraph with `Send`, checkpointer, streaming, `llm.py`, fake-LLM tests, LangSmith live. A complaint flows end to end. SLA monitor ported with tests. | 03, 04 |
| **2** | RAG: corpus, ingest CLI, FAISS + hybrid + RRF, citations in four nodes, semantic cache. Semantic cluster detection, grounded daily briefing, and the email-draft chain. **Hardcoded cost/SLA/department dicts deleted.** | 05, 06 |
| **3** | Evals: golden set, metrics, judges, Ragas, three-way baseline comparison, regression gate | 07 |
| **4** | Officer ReAct agent, tools, SSE endpoint | — |
| **5** | Six frontend screens | — |
| **6** | Polish, ADRs, README with screenshots, docker-compose | 02, 08, 09, 10 |

Phase 0 documents v1 **before** deleting it.

Deferred (Phase 7, descoped by the author): human-in-the-loop `interrupt()` approval, PII redaction,
prompt-injection defense.

---

## 11. Success criteria

1. A complaint submitted through the API completes the LangGraph pipeline, and the run is inspectable
   in both LangSmith and the in-app trace viewer.
2. Killing the process mid-run and restarting resumes from the last checkpoint rather than restarting.
3. Cost estimates, SLA windows and department routing derive from retrieved documents with citations;
   no hardcoded lookup dictionaries remain in the decision path.
4. `python -m app.evals.run` produces a markdown report with all three comparison columns populated.
5. The three scheduled jobs run: SLA breaches escalate, semantically similar complaints group into one work order, and the daily briefing generates real narrative text rather than silently falling back.
6. `pytest` passes with no network access.
7. Each of the eleven documents exists and references real code in this repository.
