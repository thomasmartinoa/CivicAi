# ADR 0004 — A rejection is not a failure

**Status:** accepted, 2026-09
**Context:** v1 stored a correctly-rejected complaint — "this is a neighbour dispute,
not infrastructure" — with the same status as one the pipeline had never touched.
Nobody could tell them apart, so nobody could count either.

## Decision

Two distinct fields on the state and the row:

- `terminal_reason` — the complaint was **correctly rejected**. The run succeeded.
- `errors` — something **broke**. The run did not do its job.

## Why

- They demand opposite responses. A rejection may need an appeal path; a failure needs
  a retry.
- Counting them together makes both numbers meaningless. "18% of complaints did not
  complete" says nothing if it mixes neighbour disputes with provider outages.
- The resume sweep must re-drive failures and must never re-drive rejections —
  re-running a rejected complaint would spend quota re-deciding something already
  decided, and re-running a *resolved* one would try to issue a second work order
  against a unique column.

## What it costs

- Every consumer must handle three outcomes rather than two. The evidence panel renders
  a `terminal_reason` amber and captioned "Rejected — not a failure"; the trace viewer
  shows `step_limit` separately from `completed`; the public dashboard excludes
  rejected complaints entirely, because a rejection is a judgement about a person's
  report.
- It is easy to regress. Tests pin that a rejected complaint is stored as `rejected`
  with a reason and no work order, and that the resume sweep skips it.
