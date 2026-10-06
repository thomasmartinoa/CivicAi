# ADR 0006 — Never report a number the code cannot produce

**Status:** accepted, 2026-09
**Context:** The eval harness and the officer dashboards both compute aggregates over
samples that are sometimes empty.

## Decision

A metric with no samples is `None`, never `0.0`. A cost with no configured rates prints
`not configured`. Every metric carries the `n` it was computed over. An unmeasured
eval metric is **not written at all** — `EvalResult.value` is `NOT NULL` so that an
unmeasured figure cannot be stored as one.

## Why

- `0.0` and "not measured" look identical downstream and mean opposite things. A median
  resolution time of 0 hours reads as *instant service*; an SLA compliance rate of 1.0
  over zero completed orders reads as a *perfect record*.
- The regression gate compares against a stored baseline. A fabricated zero in that
  file would make the gate compare against a number nothing produced.
- **This rule has caught four reporting bugs in this project's own tooling**, including
  an injection slice scoring 0.00 for a configuration that had no risk model at all,
  and a `recall@k` printing 7/7 while six cases had errored.

## What it costs

- Every consumer must handle null. The frontend renders "No data" in four places rather
  than a number, and the types say `number | null` with a comment explaining why.
- It is less convenient. `sum(xs) / len(xs)` becomes a guard and a branch.
- A reader must understand that a **missing** metric means not measured. The eval
  dashboard's schema docstring says so, because an absent row is easy to misread as a
  zero that was not rendered.
