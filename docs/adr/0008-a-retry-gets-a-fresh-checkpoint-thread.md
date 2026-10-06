# ADR 0008 — A retry runs on a fresh checkpoint thread

**Status:** accepted, 2026-10
**Context:** A gas-cylinder leak was validated, classified `FIRE_HAZARD` at 0.99
confidence, and then lost `assess_risk` to a transient 503. Re-driving it failed again
in 20 ms with a byte-identical error, having made no model call at all.

## Decision

`run_complaint` uses the complaint id as its thread for a first attempt, and
`{complaint_id}:retry{n}` once the complaint has a failed `AgentRun`. The failed
thread's checkpoint is left in place.

## Why

- A node that fails **does not raise** — it returns `{"errors": [...]}`, deliberately,
  because retrieval is a soft dependency (ADR 0003). LangGraph cannot tell that update
  apart from a successful one, so the failed node is checkpointed as **complete**, and
  re-invoking the same thread replays the stored error without calling the model.
- Making the complaint merely *eligible* for resumption achieved nothing on its own.
  Both halves were needed: `UNFINISHED` gained `failed` (bounded by
  `MAX_RESUME_ATTEMPTS`), and the retry needed a thread where the nodes actually
  re-execute.
- The eval harness had the identical bug and the identical fix a phase and a half
  earlier — `load_log` excludes errored rows so `--resume` cannot bake in an outage.
  The shape of a bug recurs across layers that look nothing alike.

## What it costs

- **A retry re-runs nodes that already succeeded**, which costs quota. On the free tier
  a full re-run is ~8 calls. The alternative was a complaint that could never recover.
- Checkpoint storage grows per attempt rather than per complaint.
- `graph_thread_id` on a retried complaint no longer equals its id, so anything joining
  on that assumption breaks. The runner writes the attempt's own thread, so the
  complaint points at the checkpoint that actually produced its result.
- An interrupted run — one with no failed `AgentRun` — still keeps the bare complaint
  id and resumes as before. There is a test for exactly that, because the fix must not
  break the case the checkpointer was built for.
