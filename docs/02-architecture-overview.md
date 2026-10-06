# 02 — Architecture overview

What the system is, what happens to a complaint, and why the pieces are arranged this
way. Every path below is real and can be opened.

---

## 1. The shape

```
backend/app/
  ai/
    graph/      state, nodes, edges, build, runner  — the pipeline
    prompts/    registry keyed on (name, version)
    rag/        embeddings, chunking, FAISS store, retrievers, ingest, cases, corpus/
    agents/     officer_chat.py — the ReAct loop
    tools/      officer.py — read-only, tenant-bound tools
    llm.py      the ONLY module that builds a chat model
    cache.py    semantic cache
    observability.py
  api/          HTTP + WebSocket + SSE
  db/models/    18 tables
  services/     geocoding, media, notify, sla, clustering, briefing, email_draft,
                analytics, auth, otp, chat_log, scheduler, execution, streaming
  evals/        the harness — a consumer of the app, never a dependency
```

Three import rules are enforced by `tests/test_import_rules.py`:

- `app/api/` must not import `app/ai/graph/` directly; it goes through
  `ai/graph/runner.py`.
- `app/ai/` must not import `app/api/`. **The entire AI system runs from a script or a
  pytest with no HTTP layer.**
- Nothing may import `app/evals/`. The harness measures the app; the app must not
  depend on its own measuring instrument.

Two more rules, added in Phase 4b, are enforced by walking the AST of `app/ai/tools/`:
no tool may take a parameter containing "tenant", and no tool may write.

---

## 2. What happens to a complaint

### 2.1 Submission is fast and the work is not

`POST /complaints/` stores the complaint, saves any media, returns a tracking id, and
schedules the graph **without awaiting it** (`app/services/execution.py`). The citizen
gets a response in milliseconds; the pipeline takes two to three minutes at the free
tier's rate limit.

v1 did the same thing and the latency argument was right. What v1 could not do was
notice that a run had been interrupted: a restart mid-pipeline left the complaint at
`submitted` for ever with nothing to retry it.

### 2.2 The graph

```
intake → [analyse_media ⇉] → validate → classify → ⟳ investigate → assess_risk → route → work_order → notify
```

- `intake` geocodes and fans out one `analyse_media` branch per uploaded file, using
  LangGraph's `Send`.
- `validate` decides whether this is an infrastructure complaint at all.
- `classify` picks one of twelve categories. Below `CONFIDENCE_THRESHOLD` (0.7) it
  branches to `investigate`, which re-reads the taxonomy with a widening search and
  loops at most `MAX_INVESTIGATE_TURNS` (3) times.
- `assess_risk` scores 0–100 and sets the risk band, which sets the SLA window.
- `route` picks the department from the SOP and the contractor by score.
- `work_order` estimates cost from the rate card.
- `notify` emails the citizen and broadcasts to the WebSocket.

Four of those nodes retrieve evidence and record citations. See `docs/05`.

### 2.3 Persistence and resumption

Each node's output is checkpointed. `run_complaint` re-invokes rather than replays, so
an interrupted run continues where it stopped.

**A failed run is a different case and it took two attempts to get right.** A node that
fails does not raise — it returns `{"errors": [...]}`, deliberately, because retrieval
is a soft dependency — so LangGraph checkpoints it as *complete*. Re-invoking the same
thread therefore replays the stored error without calling the model. A retry now runs
on its own thread (`_thread_for` in `ai/graph/runner.py`), and the startup sweep
includes `failed` complaints, bounded by `MAX_RESUME_ATTEMPTS`.

That bug abandoned a correctly-classified gas-cylinder fire hazard twice. See
`docs/07` §5 and Phase 4a's carried-forward section.

---

## 3. The three surfaces

| Surface | Auth | Notes |
|---|---|---|
| **Citizen** | none, then an emailed one-time code | `POST /complaints/`, `GET /complaints/track/{id}`, and an OTP flow that returns a short-lived token. `/complaints/my` takes the address from that token and **ignores** the `email` query parameter the v1 frontend sends. |
| **Officer** | JWT, role `officer` or `admin` | The queue, work orders, analytics, the briefing, email approval, agent traces, the knowledge base, evaluation, and `POST /admin/chat` (SSE). |
| **Public** | none | `GET /public/dashboard`. Built by exclusion — see §5. |

---

## 4. Background work

`app/services/scheduler.py` runs four jobs on APScheduler:

| Job | Schedule | What it does |
|---|---|---|
| `sla_monitor` | interval | Escalates work orders past 50% and 75% of their window |
| `cluster_detection` | interval | Groups semantically similar nearby complaints into one work order |
| `daily_briefing` | cron, `BRIEFING_HOUR` | Writes the officer's morning narrative |
| `cases_refresh` | cron, an hour earlier | Rebuilds the resolved-complaint precedent index |

All four are tenant-scoped and all four are skippable with `BACKGROUND_JOBS_ENABLED=false`.

---

## 5. The rules that shape the code

**Nodes never construct a model, a retriever or a session.** Dependencies arrive
through `config["configurable"]` (`ai/graph/deps.py`). A node that built its own model
could not be tested, because LangChain's fake chat models raise on
`with_structured_output`.

**Retrieval is a soft dependency.** A missing index records
`errors: ["<node>: retrieval unavailable: …"]` and the node still produces output. The
SLA window, the department and the tracking id never wait on the index. The cost is
that a complaint processed during an outage is ungrounded and nothing else would say
so — which is why `/admin/corpus` exists.

**A rejection is not a failure.** `terminal_reason` means correctly rejected; `errors`
means something broke. v1 conflated them, so a rejected complaint was stored looking
exactly like an unprocessed one.

**Nothing outside `services/` and `evals/` computes a number.** The officer API, the
agent's tools and the screens all read the same SLA bands from `services/sla.py` and
the same contractor scoring from `route.score_contractor`. An agent that recomputed
either would drift from the system it describes, leaving an officer with two answers
and no way to tell which was real.

**Everything is tenant-scoped, and the public dashboard is built by exclusion.** The
admin schemas list what to include; `app/schemas/public.py` lists what is deliberately
absent — description, address, exact coordinates, routing justification, evidence and
all media — and why.
