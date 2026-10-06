# 05 — RAG explained

How a decision in this system gets a citation: what is chunked, how it is indexed, how
it is retrieved, and what the measurement says it is worth.

---

## 1. The corpus is authored, not scraped

`app/ai/rag/corpus/` holds 16 markdown documents — 100 chunks — written for this
project: a category taxonomy, a citywide SLA policy, a contractor scoring policy, a
municipal rate card, and twelve departmental SOPs.

They are authored because they are the *ground truth the system is accountable to*.
When `route` says "Public Works owns road surface defects [1]", the citation has to
point at a document a human could disagree with. A scraped corpus would make the
citation decorative.

This is also where the hardcoded dictionaries went. v1 had cost tables, SLA windows
and department mappings as Python dicts in the decision path; Phase 2 deleted them and
`tests/ai/rag/test_corpus.py` asserts the corpus and the code still agree.

---

## 2. Two corpora, two chunking strategies

`app/ai/rag/chunking.py`:

- **Policy documents are split on markdown headers.** Each chunk stays inside one
  section and records its header path, so a hit is cited as
  `sop_roads.md › Public Works Department — Road Surface SOP › Escalation` rather than
  "chunk 17".
- **Case records are one chunk each.** A resolved complaint is short and
  self-contained; splitting it would separate a description from its outcome.

The header path is not cosmetic. It is the citation format the graph records in
`evidence`, the format the officer agent quotes, and the format the evidence panel
renders — one string, produced once, readable by a person.

**The header trail lives in metadata, not in the chunk text**, and that caught a bug:
two retrieval eval cases were written to match on a section heading and reported
permanent misses while the correct chunk was arriving at rank 1. There is now a test
that refuses a case defined by a header match.

---

## 3. Embedding and indexing

`gemini-embedding-001` at 768 dimensions, unit-normalised, in a FAISS `IndexFlatIP` —
inner product over unit vectors is cosine. Chunks and metadata sit in a JSON sidecar in
index order, and a manifest stamps the model tag.

Why not pgvector: `docs/adr/0002-faiss-over-pgvector.md`, including what it costs —
FAISS cannot filter by metadata, so every retriever over-fetches and filters in Python.

**The manifest matters more than it looks.** An index built with a different embedder
than the one configured retrieves nonsense rather than failing, so the model tag is
recorded and surfaced on `/admin/corpus`.

---

## 4. Hybrid retrieval with Reciprocal Rank Fusion

Dense retrieval misses exact terms; BM25 misses paraphrase. The system runs both and
fuses the rankings:

```python
def rrf_merge(rankings: list[list[Hit]], *, rrf_k: int = 60) -> list[Hit]:
    """score = Σ over rankings of 1 / (rrf_k + rank)"""
```

**The input scores are discarded on purpose** — a cosine and a BM25 score are not
comparable, and normalising them would be inventing a comparison. RRF uses only rank,
which is why it works across retrievers that disagree about what a score means.

`rrf_k=60` is the value from the original paper; it damps the advantage of being first
in any one list.

---

## 5. Grounding a node

`app/ai/graph/retrieval.py` is the seam. `retrieve()` returns `RetrievedChunk`s ready
for `state["evidence"]`, and `format_evidence()` turns them into the numbered block a
prompt cites by `[n]`.

**It never raises.** A missing index, a mismatched embedder or a dead retriever returns
an empty result with an error string; the node records it and carries on:

```python
def retrieve(retriever, query, *, node, k=4, filters=None) -> RetrievalResult:
    if retriever is None:
        return RetrievalResult(error=f"{node}: retrieval unavailable: no retriever configured")
    try:
        hits = retriever.search(query, k=k, fetch_k=DEFAULT_FETCH_K, filters=filters)
    except Exception as exc:
        return RetrievalResult(error=f"{node}: retrieval unavailable: {exc}")
```

That is the soft-dependency rule: **the SLA window, the department and the tracking id
never wait on the index.** The cost is that a complaint processed during an outage is
routed on the model's own judgement and nothing else in the system would say so —
which is why `/admin/corpus` exists and why the evidence panel says "no citations
recorded" in amber rather than hiding the section.

Four nodes retrieve: `classify` (taxonomy), `investigate` (taxonomy, widening),
`assess_risk` (SLA policy and precedent), `route` (SOP and contractor scoring),
`work_order` (rate card).

---

## 6. Precedent: resolved complaints as a second corpus

`app/ai/rag/cases.py` indexes resolved complaints so `assess_risk` can see how similar
past reports were actually scored. The index is rebuilt nightly by a scheduled job and
every case record carries its `tenant_id`, because precedent from another municipality
is not precedent.

---

## 7. The semantic cache

`app/ai/cache.py`. An exact-match cache misses the moment a citizen writes "pot hole"
instead of "pothole", so this one embeds the prompt variables and returns the stored
completion when the nearest previous prompt scores above a cosine threshold.

One cache per chain — a classification must never be served as a risk assessment. In
memory and per process on purpose: the point is to skip a model call for the burst of
near-identical complaints a single incident produces, not to be a durable store.

---

## 8. What it is actually worth

From the three-column sweep on the 100-item golden set (`docs/eval-reports/`):

| Configuration | macro-F1 |
|---|---|
| Keyword baseline, no model | 0.54 |
| Model, **no retrieval** | 0.81 |
| Model **with retrieval** | **0.93** |

Retrieval buys about +5 points of accuracy but **+12 of macro-F1**. That gap is the
finding: macro-F1 weights every category equally, so retrieval helps most on the rare
categories — the ones a keyword system and an ungrounded model both get wrong.

**And the honest other half.** Grounding `assess_risk` moved it from 0.63 to 0.66,
which does not clearly pay for itself, and that was measured on the wrong model tier
anyway. **Faithfulness is unmeasured**: citations are checked for shape, never for
whether the cited passage actually supports the sentence. A node can cite a real
document and still say something the document does not support, and nothing in this
project would catch it.
