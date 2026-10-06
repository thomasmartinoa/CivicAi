# ADR 0002 — FAISS with a JSON sidecar, not pgvector

**Status:** accepted, 2026-09
**Context:** Phase 2a needs a vector store for a few thousand policy and case chunks.

## Decision

FAISS `IndexFlatIP` over unit-normalised 768-dimensional vectors, with chunks
and metadata in a JSON sidecar in index order, and a manifest stamping the
embedding model tag. SQLite remains the relational store.

## Why

- Zero infrastructure: no Postgres, no extension, nothing to run in docker for
  local development. The whole system still starts with one command.
- `faiss-cpu` ships cp314 wheels; nothing else in the stack needed to move.
- Exact search (no IVF training) is correct at this scale and has no tuning knobs
  to get wrong.

## What it costs

- **No metadata filtering.** FAISS returns nearest neighbours by vector alone.
  Every retriever over-fetches `fetch_k=50` and filters in Python. Below ~10k
  chunks this is negligible; at 100k it would not be. pgvector would push the
  filter into SQL (`WHERE district = ? ORDER BY embedding <=> ?`).
- **Two stores to keep consistent.** The index and the `document_chunks` table
  describe the same chunks. The ingest CLI rebuilds the index from scratch each
  run so they cannot drift, at the cost of re-embedding unchanged text — which
  is why `Document.content_hash` skips the DB write but not the embed. Files
  removed from the corpus have their rows pruned on the next run, so deletion
  cannot drift either. Each collection gets its own index directory
  (`<rag_index_dir>/policy`, later `<rag_index_dir>/cases`), so rebuilding one
  never touches the other.
- **No concurrent writers.** One process rebuilds the index; readers load it.

## When to revisit

The moment case records (Phase 2b) push the corpus past ~10k chunks, or the
moment a second writer is needed. The `FaissStore` interface is small enough
that a `PgVectorStore` with the same `add`/`search`/`save`/`load` shape is a
contained change.
