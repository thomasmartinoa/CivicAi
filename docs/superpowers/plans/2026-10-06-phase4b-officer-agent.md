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

## Carried forward

Filled in when the phase lands.
