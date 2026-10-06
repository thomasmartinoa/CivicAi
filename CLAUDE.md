# CLAUDE.md

Guidance for Claude Code working in this repository. Everything below describes
**v2**, the current system. v1 was deleted in Phase 0; `docs/01-legacy-system-explained.md`
records what it was and why it was replaced, and is the only place v1 is described.

## What this is

An AI-driven municipal complaint pipeline. A citizen submits a report (text, photos,
voice, GPS); a LangGraph graph validates it, classifies it into one of twelve
categories, scores its risk, routes it to a department and contractor, drafts a work
order with an SLA deadline, and notifies the citizen. Every AI decision cites the
municipal documents it was grounded in.

The project is built in phases, each with a plan under `docs/superpowers/plans/` and
a **"Carried forward"** section at the end recording what was deliberately deferred.
**Read the carried-forward section of the most recent phase before starting work** —
it is where the known defects live.

| Phase | What landed |
|---|---|
| 0 | v1 deleted, config, 17 models, baseline migration, seed, app boots |
| 1a–1c | `llm.py`, the graph, checkpointing, media subgraph, HTTP + WebSocket streaming |
| 2a | RAG: corpus, chunking, FAISS, hybrid retrieval with RRF, ingest CLI |
| 2b | Four nodes grounded with citations, `investigate` loop, case records, semantic cache, SLA monitor |
| 2c | Semantic clustering, daily briefing, officer email draft, scheduled jobs |
| 3 | Golden set, three-column eval, judges, regression gate, observability |
| 4a | Officer auth, the complaint queue, work orders, analytics, briefing, email approval, citizen OTP + tokens, the public dashboard |
| 4b | Officer ReAct agent: six read-only tenant-bound tools, the loop, `POST /admin/chat` over SSE, transcripts on `agent_runs`/`agent_steps` |
| 5 | Six screens: officer chat, agent traces, evidence panel, live pipeline, knowledge base, evaluation — each rendered and looked at |
| 6 | Eleven docs, eight ADRs, README, docker-compose reviewed and fixed |

## Commands

```bash
cd backend
.venv/bin/python -m pytest -q                       # 904 tests, no network, no key, ~20s
.venv/bin/python -m uvicorn app.main:app --reload   # API on :8000
.venv/bin/python -m alembic upgrade head            # 5 migrations
.venv/bin/python -m app.ai.rag.ingest --collection all   # build the FAISS indexes
.venv/bin/python -m app.evals.run --config all --flash-only --resume  # the eval sweep
```

The frontend under `frontend/` has twelve screens and builds clean. Phase 5 rebuilt
six of them against the real API and added officer navigation; the citizen feedback
screens still call three endpoints that do not exist (rating, fix verification,
completion photo — see Phase 4a's carried-forward).

**A screen is not done until it has been rendered and looked at.** Phase 5 verified
every screen in headless Chromium against a live backend, which found five bugs that
`tsc` and curl both missed — including a detail screen that read a field the v2 API
has never sent, hiding four phases of grounding work behind a passing type check.
Screenshots are in `docs/screenshots/`.

## Architecture

```
backend/app/
  ai/
    graph/        state, nodes, edges, build, runner  — the pipeline
    prompts/      registry keyed on (name, version)
    rag/          embeddings, chunking, FAISS store, retrievers, ingest, cases, corpus/
    agents/       officer_chat.py — the ReAct loop, the only LLM-driven control flow
    tools/        officer.py — read-only, tenant-bound @tool functions
    llm.py        the ONLY module that builds a chat model
    cache.py      semantic cache
    observability.py  @traced, run metadata
  api/            citizen-facing HTTP + WebSocket
  db/models/      SQLAlchemy models
  services/       geocoding, media, notify, sla, clustering, briefing, email_draft, scheduler
  evals/          the eval harness — a consumer of the app, never a dependency
```

### The graph

`GRAPH_VERSION = "2b.0"`. Nine nodes:

```
intake → [analyse_media ⇉] → validate → classify → ⟳ investigate → assess_risk → route → work_order → notify
```

`classify` branches to `investigate` below `CONFIDENCE_THRESHOLD` (0.7), which loops
at most `MAX_INVESTIGATE_TURNS` (3) times, widening its taxonomy search each turn.
`intake` fans out one `analyse_media` branch per uploaded file.

### Rules that are load-bearing

- **Nodes never construct a model, a retriever or a session.** Dependencies arrive
  through `config["configurable"]` (`ai/graph/deps.py`). Tests inject a
  `RunnableLambda` for a chain and a small stub for a retriever. A node that built
  its own model could not be tested, because LangChain's fake chat models raise on
  `with_structured_output`.
- **Retrieval is a soft dependency.** A missing index or a dead retriever records
  `errors: ["<node>: retrieval unavailable: …"]` and the node still produces its
  output. The SLA window, the department and the tracking id never wait on the index.
- **A rejection is not a failure.** `terminal_reason` means the complaint was
  correctly rejected; `errors` means something broke. v1 conflated them, which is why
  a rejected complaint was stored looking exactly like an unprocessed one.
- **Every Pydantic class in `ComplaintState` must be in `CHECKPOINT_ALLOWLIST`**
  (`ai/graph/state.py`). A missing class deserialises as a plain dict rather than
  raising, and the failure surfaces much later as an `AttributeError`.
- **No hardcoded municipal values in the decision path.** Costs come from the rate
  card, SLA windows from `Tenant.config`, departments from `CATEGORY_DEPARTMENT`.
  `tests/ai/rag/test_corpus.py` asserts the corpus and the code agree.
- **Everything is tenant-scoped.** `route` fails closed without a `tenant_id`;
  `assess_risk` retrieves no precedent without one. An unscoped query spans tenants.
- **`app/ai/` must not import `app/api/`**, and nothing may import `app/evals/`.
  `tests/test_import_rules.py` enforces both.
- **No tool in `app/ai/tools/` may take a `tenant_id`, and none may write.** The
  tenant is bound in a closure the model cannot reach, so no parameter exists for an
  LLM to fill with somebody else's id — the agent's context contains complaint text
  written by the public. Both rules have a test that was verified by breaking the code
  and watching it fail.
- **Prompts are versioned and old versions stay registered.** `classify` v1 and
  `assess_risk` v1 are the ungrounded baselines the eval compares against; deleting
  them would make that comparison unrepeatable.

## Configuration

`backend/.env`, loaded by `app/config.py`. `.env.example` documents every field and
`tests/test_config.py` fails if a setting is missing from it.

```
GEMINI_API_KEY=            # required for anything live
GEMINI_MODEL=gemini-3.5-flash-lite     # model ids expire; a 404 on every node means check these
GEMINI_MODEL_STRONG=gemini-3.5-flash
LLM_REQUESTS_PER_SECOND=0.2            # the free tier allows 15 generate requests/minute/model
LLM_MAX_RETRIES=0                      # provider-side retries bypass the rate limiter; see llm.py
LLM_TIMEOUT_SECONDS=60                 # without it a stalled connection hangs a run forever
BACKGROUND_JOBS_ENABLED=true           # SLA monitor, clustering, briefing, cases refresh
```

**Free-tier quotas, measured:** flash-lite 500/day and 15/minute; the strong tier
20/**day**; embeddings 100/minute. A full eval sweep is ~555 calls, so it fits in one
day and leaves little over. `--flash-only` keeps a sweep off the strong tier.

## Testing

904 tests, no network, no API key, about twenty seconds. Three things to know:

- **Fakes everywhere, and a fake looser than reality is worse than none.**
  `FakeEmbedder` is content-hashed, so only *identical* text is similar under it — a
  similarity threshold tested with it is vacuous, which is why
  `tests/services/test_clustering.py` carries a small bag-of-words embedder instead.
  Phase 4b hit the sharper version of this twice: a retriever fake with a looser
  signature than the real protocol, and a chat fake returning `content` as a string
  where the provider returns a list of blocks. Both made a green suite over code that
  could not run. **Copy the real signature and the real payload shape, even when the
  loose version is easier.**
- **Every unit test passing does not mean the system works.** All six production
  bugs this project has found came from live runs, never from the suite: retired
  model ids, no request timeout, `AgentRun.finished_at` landing before `started_at`,
  the rate limiter being bypassed by the provider client's own retries, a transient
  503 permanently abandoning a complaint, a resume that replayed the failed node's
  cached error instead of retrying it, and two Phase 4b bugs where the test fake was
  looser than reality. Run something real before trusting a change.
- **The eval harness is the other half of the test suite.** `app/evals/` measures
  what pytest cannot: whether retrieval helps, whether a threshold is right, whether
  a prompt change is an improvement or a trade. `docs/07-evaluation-and-observability.md`
  has the current numbers and, more usefully, what is *not* measured.

## Documentation

`docs/00-README.md` is the index. Eleven numbered documents, each explaining a concept
through this repository's own code and saying what was rejected. `docs/adr/` has one
file per contested decision, each ending with **what it costs** rather than why it was
obviously right.

Read `docs/07` §5 if you are sceptical, and the **Carried forward** section of the most
recent phase plan before changing anything.

## Where the known defects are

`docs/07-evaluation-and-observability.md` §5 and the carried-forward sections of the
phase plans.

**`validate` is on v2 as of 2026-10-06.** The A/B
(`docs/eval-reports/2026-10-06-validate-v1-vs-v2.md`) was a trade, not a clean win:
over n=40, v1 wrongly rejected 9 real complaints and admitted no junk; v2 wrongly
rejects 3 and admits 1. It was promoted on the judgement that a terminal rejection
with no appeal path costs a citizen far more than a junk row costs an officer. v1
stays registered so the comparison is repeatable.

**The core baseline is stale as a result.** macro-F1 0.93 was measured with v1 in
front of `classify`, and v2 admits a slightly harder population. `core.json` records
`validate_version` and says so. A re-baseline is a full sweep (~555 calls) and needs a
day with the budget free.

## Conventions

- **Commit messages carry no trailers.** No `Co-Authored-By`, no `Claude-Session`.
  Imperative subject, body explains *why*. Check with
  `git log -1 --format=%B | grep -ci co-authored` → `0`.
- Tests are written before the code, and their names are sentences.
- A docstring on every module saying what it is for and what was rejected; a comment
  on the non-obvious line. The reader is an intermediate Python programmer.
- **Never report a number the code cannot produce.** A metric with no samples is
  `None`, not `0.0`; a cost with no configured rates prints `not configured`; a
  metric carries the `n` it was computed over. This rule has caught four reporting
  bugs in this repository's own tooling.
