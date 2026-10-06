# ADR 0005 — The officer agent is read-only, and its tools cannot name a tenant

**Status:** accepted, 2026-10
**Context:** Phase 4b gives officers a ReAct agent over their department's data. Its
context contains complaint text written by members of the public.

## Decision

Two structural constraints, enforced by tests that read the source:

1. **No tool accepts a tenant.** `build_officer_tools(session_factory, *, tenant_id)`
   closes over the department; the tools it returns have no such parameter.
2. **No tool writes.** No `session.add`, `commit`, `delete`, `merge` or `flush`.

## Why

- A tool's schema is generated from its Python signature, so a `tenant_id` parameter is
  a parameter **an LLM fills** — from a context containing citizen text. This project
  measured that such text moves a risk band in 1 of 6 golden-set injection items. A
  signature that cannot express the wrong tenant beats a prompt that asks nicely.
- Human-in-the-loop `interrupt()` approval is deferred to a later phase, so there is no
  mechanism by which an officer confirms an agent action *before* it happens. Shipping
  mutation tools first would put an LLM in charge of a municipal work order with
  nothing in between.
- Both properties are the kind that silently stop being true. An AST-walking test fails
  on any parameter containing "tenant"; another greps the module for write calls. Both
  were verified by breaking the code deliberately and watching them fail.

## What it costs

- **The agent cannot do the obvious next thing.** An officer who asks it to reassign a
  work order is told which screen does that instead. That is a worse product and a
  defensible one.
- A new tool must be added to the factory rather than written freely, and anyone adding
  one has to understand why.
- Read-only means the agent can be *wrong* without being *dangerous*, which is the
  trade being made.
