# ADR 0001 — LangGraph, not a sequential pipeline

**Status:** accepted, 2026-09
**Context:** v1 called itself a seven-agent system. It was a `for` loop over seven
classes, each calling an LLM in order, with no branching, no retries and no memory of
having started.

## Decision

Model the pipeline as a LangGraph `StateGraph` with a typed state, conditional edges,
one cycle and a checkpointer.

## Why

- **Branching.** `classify` cannot always decide. Below 0.7 confidence the run takes an
  `investigate` loop that re-reads the taxonomy with a widening search. A loop cannot
  express that without a flag and an `if` in the middle of the sequence.
- **Fan-out.** One complaint can carry several photos. `Send` gives one branch per
  file; the list reducer merges them.
- **Resumption.** v1's headline operational failure was that a restart mid-pipeline
  left a complaint at `submitted` for ever with nothing to retry it. Checkpointing
  means a run continues where it stopped.
- **Testability.** Edges are pure functions of state, so the routing rules are unit
  tested without building a graph.

## What it costs

- **A real dependency and a real learning curve.** Reducers, `Send`, the checkpoint
  allowlist and the recursion limit are all things a plain loop does not make you
  learn. Two bugs here came from getting them wrong — a missing allowlist entry
  deserialises as a dict rather than raising, and a failed node is checkpointed as
  complete.
- **The graph is harder to read than a sequence.** `build.py` plus `edges.py` plus nine
  node modules is more files than one orchestrator.
- **Checkpoint storage grows.** Every node's output is persisted per thread, and a
  retry now opens a second thread rather than reusing the first.
