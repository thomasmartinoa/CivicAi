# 08 — Code walkthrough

File by file: what it does, and the one thing about it a reader would otherwise have
to discover. Read `docs/02` first for the shape.

---

## `app/ai/graph/`

| File | What | The non-obvious bit |
|---|---|---|
| `state.py` | `ComplaintState`, the TypedDict every node reads and writes | Four fields carry `operator.add` reducers because fan-out branches write them concurrently. Every Pydantic class reachable from state must be in `CHECKPOINT_ALLOWLIST` — a missing one deserialises as a plain dict instead of raising. |
| `edges.py` | Conditional-edge predicates, as pure functions | Every one fails closed. `after_classify` deliberately does **not** check `state["errors"]`: that list accumulates and is never cleared, so an unrelated upstream soft error would end a healthy run. |
| `deps.py` | `GraphDeps` — the chains, retrievers and callables a node receives | Documents the retriever protocol: `.search(query, *, k, fetch_k, filters)`. Keyword-only in all three, and a fake that is looser has already caused one production bug. |
| `build.py` | Assembles and compiles the graph | `GRAPH_VERSION` lives here and is stamped on every run. |
| `runner.py` | Invoke or stream, then persist | `_thread_for` gives a **retry** its own checkpoint thread, because a failed node is checkpointed as complete and re-invoking the same thread replays its error without calling the model. Also: this function closes the session it is given, so a caller must not hold ORM objects across the call. |
| `retrieval.py` | The seam between the graph and RAG | `retrieve()` never raises. `DEFAULT_FETCH_K = 200` because FAISS cannot filter and the whole index is small. |

### `app/ai/graph/nodes/`

| Node | Does | Note |
|---|---|---|
| `intake.py` | Reverse-geocodes, fans out `Send` per media file | Geocoding failure is a soft error; the complaint still proceeds. |
| `media.py` | Vision over one image per branch | Appends to a reduced list, so branch ordering does not matter. |
| `validate.py` | Is this an infrastructure complaint? | **Currently the system's weakest link** — see `docs/07` §5. |
| `classify.py` | One of twelve categories, with confidence | Retrieves the taxonomy. Below 0.7 the run goes to `investigate`. |
| `investigate.py` | Re-reads the taxonomy and asks again | Widens `k = 2 + turn`; a failed turn still counts, so a broken retriever cannot loop for ever. |
| `assess_risk.py` | 0–100 score and a risk band | Retrieves the SLA policy and precedent. The band sets the SLA window. |
| `route.py` | Department from the SOP, contractor by score | `score_contractor` is reused by the officer agent's `contractor_options`, so the agent cannot disagree with the pipeline. |
| `work_order.py` | Cost estimate and SLA deadline | `estimated_cost` is optional and `0.0` is treated as a refusal, because a required number turned "I cannot price this" into "free". |
| `notify.py` | Emails the citizen, broadcasts to the socket | Best-effort; a dead relay does not fail the run. |

---

## `app/ai/` (the rest)

| File | What | Note |
|---|---|---|
| `llm.py` | The **only** module that builds a chat model | Task tiering, the shared rate limiter, fallbacks. `TASK_MODEL` is an import-time snapshot — monkeypatching `settings` does not affect it. |
| `prompts/templates.py` | Every prompt, versioned | Separates template injection from model injection, and says which defence addresses which. |
| `prompts/__init__.py` | `PROMPT_REGISTRY` and `LATEST` | Old versions stay registered: `classify v1` and `assess_risk v1` are the eval's control column. |
| `schemas.py` | The Pydantic shapes the models must return | Enums stop invented categories; `ge`/`le` make an out-of-range value a validation error rather than a wrong threshold comparison. |
| `cache.py` | Semantic cache over FAISS | One per chain; in-memory on purpose. |
| `rag/chunking.py` | Header-aware markdown splitting | The header trail lives in **metadata**, not chunk text — a retrieval test that matched on a heading reported false misses. |
| `rag/retrievers.py` | Dense, BM25, hybrid with RRF | RRF discards the input scores: a cosine and a BM25 score are not comparable. |
| `rag/ingest.py` | Load → chunk → embed → index | Rebuilds from scratch each run so the index and the DB cannot drift. |
| `rag/cases.py` | Resolved complaints as precedent | Every record carries `tenant_id`; precedent from another municipality is not precedent. |
| `agents/officer_chat.py` | The ReAct loop | `MAX_AGENT_STEPS` is a **quota** control. A step-limit overrun is a result with `hit_step_limit`, not an exception. |
| `tools/officer.py` | Six read-only, tenant-bound tools | No tool takes a tenant; no tool writes. Both enforced by tests that read the source. |
| `observability.py` | `@traced`, run metadata | LangSmith wiring. |

---

## `app/api/`

| File | Routes | Note |
|---|---|---|
| `complaints.py` | Submit, track, WebSocket, OTP, `/my` | `/complaints/my` **ignores** the `email` query parameter the v1 frontend sends — honouring it would undo the OTP flow entirely. |
| `admin.py` | Login, queue, detail, work orders, contractors, analytics, briefing, email approval, runs, corpus, evals | The biggest module. Another tenant's anything is 404, never 403. |
| `chat.py` | `POST /admin/chat` (SSE) | The generator must not use the request's session: a `StreamingResponse` body runs *after* the route returns. |
| `public.py` | `GET /public/dashboard` | Built by exclusion. Coordinates rounded to ~110 m **before** grouping. |
| `deps.py` | Auth dependencies | Role is read from the DB, not the token, so a demotion takes effect on the next request. |
| `system.py` | `/health` | |

---

## `app/services/`

| File | Note |
|---|---|
| `sla.py` | `WARNING_AT = 0.5`, `URGENT_AT = 0.75`, the escalation ladder. **Every other SLA figure in the system reads these**, so the agent, the emails and the dashboard cannot disagree. |
| `analytics.py` | Every dashboard number. Resolution time is measured from the **work order**, not `Complaint.updated_at`, which carries `onupdate` and would move with any later edit. Nothing returns 0 for "no data". |
| `clustering.py` | Best-first grouping of nearby similar complaints. |
| `briefing.py` | The officer's narrative, with `is_fallback` when the model never ran. |
| `email_draft.py` | Raises rather than storing half an email; refuses to overwrite approved wording. |
| `execution.py` | Background runs and the startup resume sweep. `UNFINISHED` includes `failed`, bounded by `MAX_RESUME_ATTEMPTS`. |
| `otp.py` | Codes are hashed, single-use, expiring and attempt-limited; a wrong guess costs **every** live code an attempt. |
| `auth.py` | JWT, direct bcrypt. `CITIZEN_ROLE` is deliberately not `"citizen"` so `get_current_user` can never accept one. |
| `chat_log.py` | Chat transcripts onto `agent_runs`/`agent_steps`. `started_at` is derived from the duration, not left to the column default. |
| `scheduler.py` | Four APScheduler jobs. |
| `streaming.py` | `ConnectionRegistry`; `publish` is best-effort and drops dead subscribers. |

---

## `app/evals/`

A consumer of the application, never a dependency — `tests/test_import_rules.py`
enforces it.

| File | Note |
|---|---|
| `dataset/golden_v1.jsonl` | 100 items: 88 real, 12 junk. The loader is strict — a malformed line names its line number. |
| `metrics.py` | A never-predicted class scores F1 0; an **empty sample returns `None`, not `0.0`**. |
| `configurations.py` | The three columns: `keyword`, `llm_only`, `full`. |
| `run.py` | The sweep. `take_slice` is stratified, because the first N ids are all one tag. `load_log` excludes errored rows so `--resume` cannot bake in an outage. |
| `report.py` | Prints `not applicable` and `not configured` rather than a zero, and carries each metric's `n`. |
| `gate.py` | Regression gate, tolerance 0.02. A missing baseline raises; an improvement does **not** move the baseline. |
| `prompt_ab.py` | Two prompt versions head to head. `verdict()` refuses to call a change an improvement when it moves both error types in opposite directions. |

---

## Where to start reading

1. `app/ai/graph/state.py` — what flows.
2. `app/ai/graph/build.py` — the shape.
3. One node, say `route.py` — what a node looks like.
4. `app/ai/llm.py` — how a chain is made.
5. The carried-forward section of the most recent phase plan — what is known to be
   wrong.
