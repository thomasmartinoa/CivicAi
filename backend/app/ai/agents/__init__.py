"""Agentic loops, as opposed to the deterministic graph in `app/ai/graph/`.

The spec's architecture line is "deterministic spine + scoped agentic loops": SLA
decisions must be reproducible and auditable, so LLM-driven control flow is reserved
for open-ended retrieval and conversation. This package is the second half of that
sentence and must never grow into the first.
"""
