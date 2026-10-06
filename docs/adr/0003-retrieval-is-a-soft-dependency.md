# ADR 0003 — Retrieval is a soft dependency

**Status:** accepted, 2026-09
**Context:** Four nodes ground their decisions in a FAISS index. The index is a file
built by a CLI, and it can be missing, stale, or built with a different embedder.

## Decision

A retrieval failure records `errors: ["<node>: retrieval unavailable: …"]` on the state
and the node still produces its output. `app/ai/graph/retrieval.py::retrieve` never
raises.

## Why

- The alternative makes an index problem into a **service outage for citizens**. A
  complaint that cannot be grounded can still be given a department, an SLA window and
  a tracking id, and those are the things the citizen is waiting for.
- The ingest CLI may legitimately not have run yet. The API must boot without an index.
- A node that degrades is testable; a node that raises on a missing file needs the file
  in every test.

## What it costs

**This is the expensive one, and it is worth stating plainly.** A complaint processed
during an index outage is routed on the model's own judgement, its decisions carry no
citations, and **nothing in the system would otherwise say so**. The complaint looks
normal in the queue.

Two mitigations, both added later because the cost was not obvious at first:

- `GET /admin/corpus` reports `available: false` with the ingest command, and states
  that decisions made now will carry no citations.
- The evidence panel renders "No citations recorded — this complaint was processed
  without retrieval" in amber rather than hiding an empty section.

Neither is as good as the index being there. An officer still has to notice.
