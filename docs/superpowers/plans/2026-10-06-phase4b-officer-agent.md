# Phase 4b — the officer ReAct agent, its tools, and the SSE endpoint

**Status:** planned 2026-10-06. Builds on Phase 4a's officer API (`86ae8d4`…`ac7e1ae`).

The spec says four words about this phase — *"Officer ReAct agent, tools, SSE
endpoint"* — plus one line in §8: *"SSE-streamed ReAct agent that surfaces tool calls
as they happen."* Everything below is therefore a design decision, not a transcription,
and the ones that matter are argued rather than asserted.

## What it is for

An officer asks questions in English and gets answers grounded in **this tenant's**
data and the municipal corpus: *"what's about to breach?"*, *"who should take the
Jayanagar drain job?"*, *"what does the SOP say about a collapsed culvert?"*. The
pipeline already decides; this is the surface for interrogating what it decided.

## The three rules this phase is built around

### 1. The agent cannot choose a tenant

**No tool takes a `tenant_id` argument.** It is bound into every tool at construction
time from the authenticated officer, in a closure the model cannot reach.

This is the only security property here that cannot be retrofitted. A `tenant_id`
parameter on a tool is a parameter an LLM fills from its context, and its context
contains complaint text written by members of the public. Phase 3 measured that 1 in 6
prompt-injection items still moves its risk band, so the premise that complaint text
can steer this model is not hypothetical — it is measured. A tool signature that
*cannot express* the wrong tenant is worth more than a prompt that asks nicely.

The import-lint test grows a case for this: no function in `app/ai/tools/` may accept
a parameter named `tenant_id`.

### 2. The agent is read-only

No tool changes anything. Not status, not assignment, not email approval, not
dispatch.

The spec defers human-in-the-loop `interrupt()` approval to Phase 7, which means
there is no mechanism by which an officer confirms an agent's action before it
happens. Shipping mutation tools before that mechanism exists would put an LLM in
charge of a municipal work order with nothing between the two. An officer who wants
something changed has the Phase 4a PATCH endpoints, where the transition is
allow-listed and their id lands on the row.

### 3. Every answer is traceable to a tool result

The response carries the tool calls that produced it, and the SSE stream emits them
as they happen rather than only at the end. An officer reading "three orders breach
tonight" must be able to see the query that returned three.

## The tools

All in `app/ai/tools/officer.py`, all read-only, all tenant-bound, each returning a
small dict rather than ORM objects.

| Tool | Answers | Notes |
|---|---|---|
| `search_policy(query)` | "what does the SOP say about…" | The existing `HybridRetriever` over the corpus. Returns `source › headers` citations, same shape the graph nodes record. |
| `find_complaints(category?, status?, district?, risk_level?, limit)` | "show me open WATER complaints in X" | Tenant-scoped. `limit` capped server-side. |
| `get_complaint(tracking_id)` | "what happened with CIV-…" | Includes the stored citations and routing justification, so the agent can explain a past decision rather than re-derive it. |
| `work_orders_at_risk()` | "what breaches tonight?" | Reuses `services/sla.py`'s own bands, so the agent and the emails cannot disagree. |
| `contractor_options(category)` | "who could take this?" | Reuses `route`'s scoring so the agent's suggestion matches what the pipeline would have chosen. |
| `tenant_statistics()` | "how are we doing?" | Delegates to `services/analytics.py`. Returns `None` where that returns `None`. |

**Nothing new computes a number.** Every figure comes from `services/`, for the same
reason Phase 4a put them there: an agent that recomputed SLA bands or contractor
scores would drift from the system it is describing, and the officer would have two
answers with no way to tell which was real.

## Tasks

1. **`app/ai/tools/officer.py`** — the six tools behind a `build_officer_tools(session_factory, *, tenant_id)` factory. Tests: each tool returns the right shape; each one scopes to its tenant; no tool accepts `tenant_id`; `limit` is capped; a missing tracking id is a message rather than an exception, because a raising tool ends the agent's turn.
2. **The import-lint case** — no `tenant_id` parameter anywhere in `app/ai/tools/`, and `app/ai/tools/` must not import `app/api/`.
3. **`app/ai/agents/officer_chat.py`** — the ReAct loop with `MAX_AGENT_STEPS`, built with LangGraph's prebuilt agent if it fits or hand-rolled if it does not. Tests use a scripted fake model that emits tool calls, so the loop, the bound and the transcript are all tested with no provider.
4. **The prompt** — `OFFICER_CHAT_V1` in the registry, stating that it answers only from tool results and says so when a tool returns nothing.
5. **`POST /admin/chat` (SSE)** — officer-authenticated, emits `tool_call`, `tool_result`, `token`, `done`, `error`. Tests: unauthenticated is 401, a citizen is 403, another tenant's data never appears, a provider outage is a terminal `error` event rather than a dropped connection.
6. **Persistence** — the conversation and its tool calls on `agent_runs`/`agent_steps`, so the trace viewer in Phase 5 has something to render.
7. **Live verification** — one real conversation against a real model, with the transcript in `docs/`. A ReAct turn is several calls at 0.2 req/s, so budget a handful of turns, not a demo.

## What this phase will NOT do

- **Mutation tools.** See rule 2. Written here so it is a decision and not an omission.
- **Conversation memory across requests.** Each request carries its own history from
  the client. A server-side session store is a Phase 5 concern once a screen exists
  to need it.
- **A `/public/chat`.** The corpus is municipal policy and would be reasonable to
  expose, but every tool here is tenant-bound and read-only *for an officer*; pointing
  an unauthenticated endpoint at them needs its own threat model.

## Carried forward from Phase 4b

Landed 2026-10-06 across six commits (`62940b4`…`e5613e0`), 867 tests.

### The two bugs the suite was blind to, and the one lesson

Both found by the first live conversation, both invisible to 864 passing tests, and
both the *same* mistake:

- `search_policy` called the retriever with only `k`, where the protocol is
  keyword-only in `k`, `fetch_k` and `filters`. Every call would have raised
  `TypeError` in production. The test fake was declared `search(self, query, k=5)`.
- The agent discarded its own answers. Gemini 3 returns `content` as a list of
  content blocks, and both the collector and the stream tested
  `isinstance(content, str)`. Every test used `AIMessage(content="a plain string")`.

**A fake looser than the thing it stands in for converts a crash into a green suite.**
CLAUDE.md already said this about `FakeEmbedder`; it was written twice more anyway, in
one phase. The habit worth forming: when a fake stands in for an interface that has a
declared signature or a provider-specific shape, copy that shape exactly, even when
the looser version is easier to write.

### What was deliberately not built

- **Mutation tools.** No tool changes anything, because the spec defers
  human-in-the-loop `interrupt()` approval to Phase 7 and there is therefore no
  mechanism by which an officer confirms an agent action before it happens.
- **Server-side conversation memory.** History arrives from the client each turn. A
  session store is worth building when a screen needs one; until then the simplest
  thing that cannot leak one officer's conversation into another's is to hold none.
- **A public chat endpoint.** Every tool is tenant-bound and read-only *for an
  officer*; pointing an unauthenticated endpoint at them needs its own threat model.

### Known limits

- **A turn costs three to four model calls, not one.** The model rephrases rather than
  accepting its first result set — one policy question produced three `search_policy`
  calls. At 0.2 requests per second that is a twenty-second answer and four of 500
  daily calls. `MAX_AGENT_STEPS` bounds the worst case; nothing makes the common case
  efficient. Caching repeated policy searches within a turn is the obvious next
  improvement and was not attempted.
- **Injection resistance is measured at n=1.** One live attempt was named and refused.
  Phase 3 measured 1 in 6 injection items still moving a risk band in the pipeline,
  and nothing suggests the chat surface is better. The structural defence — no tool
  can name a tenant, no tool can write — does not depend on the model, and is the only
  part of this that should be relied on.
- **An officer cannot tell a surrender from a conclusion on screen.** `hit_step_limit`
  reaches the stream and the transcript, but no UI renders it yet. Phase 5 must, or a
  step-limit message will read as an answer.
- **The transcript inherits an unanswered retention question.** `agent_steps` now
  stores officer questions and tool results, and a tool result can contain a complaint
  description written by a member of the public. Reviewability is the point; nothing in
  this project says how long any of it is kept.
- **`tenant_statistics` is the only tool that can report a null**, and the prompt is
  the only thing stopping the model rendering it as a zero. There is a unit test on
  the tool passing nulls through, and none on the model's behaviour — that would need
  an LLM judge, which Phase 3 ruled out on cost.

### Smaller things a reader will trip over

- The `tool_call` event echoes the model's arguments verbatim, and `get_complaint`'s
  refusal quotes back the tracking id it was asked for. Neither is a disclosure, but a
  Phase 5 screen renders model-generated text and should escape it.
- `OFFICER_CHAT` is on the flash tier despite being conversational prose, because the
  strong tier's free quota is 20 a **day** and a ReAct turn is several calls.
- The streaming generator must not use the request's session: a `StreamingResponse`
  body runs after the route returns, by which point `Depends(get_db)` has closed.
  `_session_factory()` is the seam, and it is also what makes the endpoint testable.
