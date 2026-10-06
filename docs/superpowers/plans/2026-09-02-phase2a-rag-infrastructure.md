# CivicAI v2 — Phase 2a: RAG Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A municipal knowledge corpus, chunked and indexed for both dense and sparse retrieval, queryable with citations — built and tested without a single network call.

**Architecture:** Everything under `backend/app/ai/rag/`. An `Embedder` protocol with a deterministic fake for tests and a Gemini implementation pinned to 768 dimensions. A `FaissStore` over `IndexFlatIP` with a JSON metadata sidecar, stamped with the embedding model tag and refusing to load a mismatch. Dense, BM25 and hybrid (Reciprocal Rank Fusion) retrievers. An ingest CLI that is idempotent on content hash and records what it indexed in the `documents`/`document_chunks` tables built in Phase 0.

**No node changes in this phase.** Phase 2b wires retrieval into the graph. This plan ends at a REPL where `HybridRetriever(...).search("pothole outside school gate")` returns cited chunks from the SOPs.

**Tech Stack:** faiss-cpu 1.15.0, rank-bm25 0.2.2, numpy 2.x, langchain-google-genai 4.4.0 (embeddings only), pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-civicai-v2-design.md` §4

**Prior phases:** 0 (foundation), 1a (AI layer), 1b (graph), 1c (HTTP + streaming) — 248 tests green. Read Phase 1c's "Carried forward into Phase 2" before starting; one item (the spec's Phase 1 table listing LangSmith and the SLA monitor) needs a documented decision, made in Task 5.

## Global Constraints

- **Python 3.14.** Virtualenv at `backend/.venv`. Tests: `cd backend && .venv/bin/python -m pytest`.
- **New pins**, verified to install alongside the current requirements and to run on 3.14 with the Phase 1 suite still green: `faiss-cpu==1.15.0`, `rank-bm25==0.2.2`, `numpy>=2.0,<3`.
- **Embedding dimension is 768, pinned.** Gemini's `gemini-embedding-001` accepts `output_dimensionality=768`; Ollama's `nomic-embed-text` is natively 768. The model tag `"<model>@768"` is stamped into every index and every `Document` row, and a store refuses to load an index built by a different tag. Silent dimension drift is a classic production RAG bug.
- **No network in tests.** Every test uses `FakeEmbedder`. No test constructs `GoogleGenerativeAIEmbeddings` or touches the real index directory.
- **No test writes into the repository.** Index files go to `tmp_path`.
- **FAISS has no metadata filtering.** We over-fetch `fetch_k` and post-filter in Python. This is the documented cost of the SQLite+FAISS choice; it is fine below ~10k chunks and an ADR says so.
- **`app/ai/` must never import `app/api/`.**
- **Test output pristine**; warning suppression narrowly scoped, never blanket.
- **Commit messages carry no `Co-Authored-By` trailer.** The repository owner asked for none.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/ai/rag/__init__.py` | package marker |
| `backend/app/ai/rag/embeddings.py` | `Embedder` protocol, `FakeEmbedder`, `GeminiEmbedder`, `EMBEDDING_DIM`, model tags |
| `backend/app/ai/rag/chunking.py` | `Chunk` dataclass; markdown-header-aware splitting for policy docs; one-chunk-per-record for cases |
| `backend/app/ai/rag/corpus/*.md` | the authored knowledge base |
| `backend/app/ai/rag/store.py` | `FaissStore` — index + metadata sidecar, save/load, tag check |
| `backend/app/ai/rag/retrievers.py` | `DenseRetriever`, `BM25Retriever`, `HybridRetriever`, `Hit`, `rrf_merge` |
| `backend/app/ai/rag/ingest.py` | load → chunk → embed → index; writes `Document`/`DocumentChunk`; CLI entry |
| `docs/adr/0002-faiss-over-pgvector.md` | the tradeoff, written down |
| `backend/tests/ai/rag/` | mirrors the above |

---

## Task 1: Embeddings — the protocol, a fake, and Gemini at 768

**Files:**
- Modify: `backend/requirements.txt`, `backend/app/config.py`
- Create: `backend/app/ai/rag/__init__.py`, `backend/app/ai/rag/embeddings.py`
- Test: `backend/tests/ai/rag/__init__.py`, `backend/tests/ai/rag/test_embeddings.py`

**Interfaces:**
- `EMBEDDING_DIM: int = 768`
- `class Embedder(Protocol)`: `model_tag: str`; `embed_documents(texts: list[str]) -> list[list[float]]`; `embed_query(text: str) -> list[float]`
- `class FakeEmbedder`: deterministic, seeded from text content, unit-normalised, `model_tag = "fake@768"`
- `class GeminiEmbedder`: wraps `GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", output_dimensionality=768)`, `model_tag = "gemini-embedding-001@768"`
- `build_embedder() -> Embedder` — Gemini when a key is configured, else raises `NoEmbedderConfigured`
- `settings.embedding_model: str = "gemini-embedding-001"`, `settings.rag_index_dir: str = "./data/index"`

- [ ] **Step 1: Add dependencies and settings**

```bash
cd backend
cat >> requirements.txt <<'REQEOF'

# ── RAG (Phase 2) ──────────────────────────────────
faiss-cpu==1.15.0
rank-bm25==0.2.2
numpy>=2.0,<3
REQEOF
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c "import faiss, rank_bm25, numpy; print('installed')"
.venv/bin/python -m pytest -q | tail -1   # expect 248 passed
```

In `backend/app/config.py`, add to `Settings` after the LLM block:

```python
    # ── RAG ───────────────────────────────────────────────────
    embedding_model: str = "gemini-embedding-001"
    rag_index_dir: str = "./data/index"
```

Add both to `backend/.env.example`; the drift test from Phase 1a will fail otherwise.

- [ ] **Step 2: Write the failing test**

```bash
mkdir -p backend/app/ai/rag backend/tests/ai/rag
touch backend/app/ai/rag/__init__.py backend/tests/ai/rag/__init__.py
```

`backend/tests/ai/rag/test_embeddings.py`:

```python
import math

import pytest

from app.ai.rag import embeddings as embeddings_module
from app.ai.rag.embeddings import (
    EMBEDDING_DIM, Embedder, FakeEmbedder, NoEmbedderConfigured, build_embedder,
)


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def test_fake_embedder_produces_the_pinned_dimension():
    vectors = FakeEmbedder().embed_documents(["a pothole", "a streetlight"])
    assert all(len(v) == EMBEDDING_DIM for v in vectors)
    assert len(FakeEmbedder().embed_query("anything")) == EMBEDDING_DIM


def test_fake_embedder_is_deterministic():
    """Two runs must index identically, or tests become order-dependent."""
    a = FakeEmbedder().embed_query("pothole on the main road")
    b = FakeEmbedder().embed_query("pothole on the main road")
    assert a == b


def test_fake_embedder_is_unit_normalised():
    """IndexFlatIP only computes cosine similarity if inputs are unit vectors."""
    vector = FakeEmbedder().embed_query("pothole")
    assert abs(_norm(vector) - 1.0) < 1e-6


def test_fake_embedder_distinguishes_different_text():
    a = FakeEmbedder().embed_query("pothole")
    b = FakeEmbedder().embed_query("streetlight")
    assert a != b


def test_fake_embedder_satisfies_the_protocol():
    assert isinstance(FakeEmbedder(), Embedder)
    assert FakeEmbedder().model_tag == f"fake@{EMBEDDING_DIM}"


def test_gemini_embedder_tag_carries_model_and_dimension():
    """The tag is what a store checks before loading an index."""
    from app.ai.rag.embeddings import GeminiEmbedder

    assert GeminiEmbedder.model_tag_for("gemini-embedding-001") == "gemini-embedding-001@768"


def test_build_embedder_fails_loudly_with_nothing_configured(monkeypatch):
    monkeypatch.setattr(embeddings_module.settings, "gemini_api_key", None)
    with pytest.raises(NoEmbedderConfigured, match="GEMINI_API_KEY"):
        build_embedder()


def test_build_embedder_does_not_dial_out_at_construction(monkeypatch):
    """Constructing a client must be free; only embedding calls the network."""
    monkeypatch.setattr(embeddings_module.settings, "gemini_api_key", "test-key")
    embedder = build_embedder()
    assert embedder.model_tag == "gemini-embedding-001@768"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_embeddings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.rag.embeddings'`

- [ ] **Step 4: Implement**

`backend/app/ai/rag/embeddings.py`:

```python
"""Embedding access, with the dimension pinned.

Gemini's embedding model can emit 768, 1536 or 3072 dimensions; Ollama's
nomic-embed-text is 768. Pinning to 768 lets either provider build an index the
other can query, and the model tag stamped into every index makes a mismatch a
loud failure rather than silently wrong nearest neighbours.
"""

import hashlib
from typing import Protocol, runtime_checkable

import numpy as np

from app.config import settings

EMBEDDING_DIM = 768


class NoEmbedderConfigured(RuntimeError):
    pass


@runtime_checkable
class Embedder(Protocol):
    model_tag: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Deterministic, offline, unit-normalised. For tests only.

    Each text seeds a random generator from its own hash, so the same text
    always maps to the same vector and different texts to different vectors —
    enough for retrieval tests to be meaningful without a model.
    """

    model_tag = f"fake@{EMBEDDING_DIM}"

    def embed_query(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        vector = np.random.default_rng(seed).standard_normal(EMBEDDING_DIM)
        vector /= np.linalg.norm(vector)
        return vector.astype("float32").tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]


class GeminiEmbedder:
    model_tag: str

    def __init__(self, model: str, api_key: str) -> None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self.model_tag = self.model_tag_for(model)
        self._client = GoogleGenerativeAIEmbeddings(
            model=f"models/{model}",
            google_api_key=api_key,
            output_dimensionality=EMBEDDING_DIM,
        )

    @staticmethod
    def model_tag_for(model: str) -> str:
        return f"{model}@{EMBEDDING_DIM}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(text)


def build_embedder() -> Embedder:
    """The real embedder, or a clear error. Never a silent fallback."""
    if settings.gemini_api_key:
        return GeminiEmbedder(settings.embedding_model, settings.gemini_api_key)
    raise NoEmbedderConfigured(
        "No embedding provider is configured. Set GEMINI_API_KEY."
    )
```

- [ ] **Step 5: Run the tests, then commit**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_embeddings.py -v`
Expected: PASS, 8 tests. Then the full suite: 256.

```bash
cd /home/martin/Projects/CivicAi
git add backend/requirements.txt backend/app backend/tests backend/.env.example
git commit -m "feat: add the embedding layer with the dimension pinned to 768

An Embedder protocol with a deterministic offline fake for tests and a Gemini
implementation at output_dimensionality=768. Every index and Document row will
carry the model tag so a dimension or model mismatch fails loudly instead of
returning silently wrong neighbours."
```

---

## Task 2: Corpus and chunking

**Files:**
- Create: `backend/app/ai/rag/corpus/` (16 markdown files), `backend/app/ai/rag/chunking.py`
- Test: `backend/tests/ai/rag/test_chunking.py`, `backend/tests/ai/rag/test_corpus.py`

**Interfaces:**
- `@dataclass(frozen=True) Chunk(text: str, source: str, chunk_id: str, metadata: dict)`
- `chunk_markdown(text: str, source: str, *, max_chars: int = 1800, overlap: int = 200) -> list[Chunk]` — header-aware; `metadata` carries `headers` (list of the H1/H2/H3 path) and `category` when the file's front matter names one
- `chunk_record(text: str, source: str, metadata: dict) -> list[Chunk]` — exactly one chunk
- `CORPUS_DIR: Path`, `load_corpus() -> list[tuple[Path, str]]`

### The corpus

Sixteen files under `backend/app/ai/rag/corpus/`. Each begins with YAML-ish front matter the loader parses:

```
---
title: Public Works Department — Road Surface SOP
collection: policy
category: ROADS
---
```

**Twelve department SOPs**, one per `Category`, named `sop_<category_lowercase>.md`. Each must contain these H2 sections, in this order, with substantive prose (target 250–400 words each, real municipal detail, not filler):

| Section | Must state |
|---|---|
| `## Scope` | what this category covers, and two explicit edge cases handed to *another* category (e.g. ROADS: "a trench dug by a utility and left unfilled is CONSTRUCTION") |
| `## Ownership` | the department name **exactly as seeded** by `app/services/seed.py`, and who the escalation officer is |
| `## Response norms` | target response windows by severity — and they must agree with `SLA_HOURS` in `app/ai/graph/nodes/work_order.py` (critical 4h, high 24h, medium 72h, low 168h) |
| `## Typical materials and cost drivers` | 4–6 concrete items and what makes a job expensive |
| `## Escalation` | the ward → block → district → city ladder and what triggers each step |

**Category assignment table** for the SOPs' `## Scope` sections, so the corpus agrees with the classifier prompt in `app/ai/prompts/templates.py`:

- ROADS: surface damage to an existing road. Hands off: unfilled utility trench → CONSTRUCTION; standing rainwater → FLOODING.
- CONSTRUCTION: building work, illegal structures, excavation left unrepaired. Hands off: surface cracks on an intact road → ROADS.
- SEWAGE: foul water, open manholes, sewer overflow. Hands off: rainwater pooling → FLOODING; solid waste → SANITATION.
- FLOODING: rainwater, waterlogging, blocked storm drains. Hands off: sewage overflow → SEWAGE.
- SANITATION: solid waste, bins, street sweeping. Hands off: liquid waste → SEWAGE.
- ELECTRICITY, WATER, PUBLIC_SPACES, EDUCATION, HEALTH, FIRE_HAZARD, STRAY_ANIMALS: author two sensible hand-offs each.

**Four policy documents:**
- `sla_policy.md` — priority bands (0–25 low, 26–50 medium, 51–75 high, 76–100 critical), the four response windows, the warning thresholds (50% and 75% of window elapsed), and the escalation ladder. Must agree with `SLA_HOURS` and `band_for_score`.
- `category_taxonomy.md` — every one of the 12 categories with a two-sentence definition and its hand-offs; this is what the Phase 2b `investigate` node retrieves when classification confidence is low.
- `rate_card.md` — a table of unit rates in ₹ for 20–30 items across categories (asphalt per m², LED luminaire, PVC pipe per metre, manhole cover, sandbag, etc.), a labour rate, and an equipment day rate. Phase 2b's `work_order` node grounds cost estimates here instead of the placeholder dict.
- `contractor_scoring.md` — the weights in `app/ai/graph/nodes/route.py` (`SPECIALISATION_WEIGHT`, `RATING_WEIGHT`, `WORKLOAD_ALLOWANCE`, `WORKLOAD_PENALTY`, `ZONE_BONUS`) explained in prose, so routing justifications can cite policy.

Write one SOP in full as the template first (`sop_roads.md`), get the tests green against it, then author the other fifteen. **Do not pad**; a short accurate section beats a long vague one.

- [ ] **Step 1: Write the failing tests**

`backend/tests/ai/rag/test_chunking.py`:

```python
from app.ai.rag.chunking import Chunk, chunk_markdown, chunk_record

SAMPLE = """---
title: Sample SOP
collection: policy
category: ROADS
---

# Sample SOP

## Scope

Roads covers surface damage. A trench left by a utility is CONSTRUCTION.

## Ownership

Public Works Department owns this category.

## Response norms

Critical within 4 hours. High within 24 hours.
"""


def test_front_matter_becomes_metadata_not_text():
    chunks = chunk_markdown(SAMPLE, "sample.md")
    assert all(c.metadata["category"] == "ROADS" for c in chunks)
    assert all(c.metadata["collection"] == "policy" for c in chunks)
    assert not any("collection: policy" in c.text for c in chunks)


def test_every_chunk_records_its_header_path():
    chunks = chunk_markdown(SAMPLE, "sample.md")
    scope = next(c for c in chunks if "trench" in c.text)
    assert scope.metadata["headers"] == ["Sample SOP", "Scope"]


def test_chunks_respect_max_chars_with_overlap():
    long_section = "## Long\n\n" + ("A sentence about roads. " * 300)
    chunks = chunk_markdown("# Doc\n\n" + long_section, "long.md", max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    # overlap: the tail of one chunk appears at the head of the next
    assert chunks[0].text[-30:] in chunks[1].text


def test_chunk_ids_are_stable_and_unique():
    a = chunk_markdown(SAMPLE, "sample.md")
    b = chunk_markdown(SAMPLE, "sample.md")
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)


def test_a_record_is_exactly_one_chunk():
    chunks = chunk_record("Pothole near school, fixed in 2 days for 8000", "case:abc",
                          {"category": "ROADS", "district": "East"})
    assert len(chunks) == 1
    assert chunks[0].metadata["district"] == "East"
    assert chunks[0].source == "case:abc"


def test_chunk_is_frozen():
    import dataclasses
    c = chunk_record("x", "s", {})
    assert dataclasses.is_dataclass(c) and c.__dataclass_params__.frozen
```

`backend/tests/ai/rag/test_corpus.py`:

```python
import re

from app.ai.graph.nodes.work_order import SLA_HOURS
from app.ai.rag.chunking import CORPUS_DIR, chunk_markdown, load_corpus
from app.constants import CATEGORY_DEPARTMENT, Category
from app.db.models.core import Department


REQUIRED_SOP_SECTIONS = [
    "## Scope", "## Ownership", "## Response norms",
    "## Typical materials and cost drivers", "## Escalation",
]


def test_there_is_one_sop_per_category():
    expected = {f"sop_{c.value.lower()}.md" for c in Category}
    present = {p.name for p, _ in load_corpus()}
    assert expected <= present, f"missing SOPs: {sorted(expected - present)}"


def test_the_four_policy_documents_exist():
    present = {p.name for p, _ in load_corpus()}
    for name in ("sla_policy.md", "category_taxonomy.md", "rate_card.md", "contractor_scoring.md"):
        assert name in present


def test_every_sop_has_the_required_sections_in_order():
    for path, text in load_corpus():
        if not path.name.startswith("sop_"):
            continue
        positions = [text.find(h) for h in REQUIRED_SOP_SECTIONS]
        assert all(p >= 0 for p in positions), f"{path.name} missing a section"
        assert positions == sorted(positions), f"{path.name} sections out of order"


def test_every_sop_front_matter_names_its_category():
    for path, text in load_corpus():
        if path.name.startswith("sop_"):
            category = path.stem.removeprefix("sop_").upper()
            assert f"category: {category}" in text, path.name


def test_every_sop_names_the_seeded_department_verbatim():
    """Routing justifications will cite this; the name must match the DB."""
    for path, text in load_corpus():
        if path.name.startswith("sop_"):
            category = Category(path.stem.removeprefix("sop_").upper())
            assert CATEGORY_DEPARTMENT[category] in text, (
                f"{path.name} does not name {CATEGORY_DEPARTMENT[category]!r}"
            )


def test_response_norms_agree_with_sla_hours():
    """The corpus and the code must not disagree about the SLA."""
    text = next(t for p, t in load_corpus() if p.name == "sla_policy.md")
    for level, hours in SLA_HOURS.items():
        assert re.search(rf"\b{hours}\s*hours?\b", text), (
            f"sla_policy.md does not state the {hours}h window for {level.value}"
        )


def test_the_rate_card_has_a_labour_rate_and_at_least_twenty_items():
    text = next(t for p, t in load_corpus() if p.name == "rate_card.md")
    assert re.search(r"labour", text, re.I)
    assert text.count("₹") >= 20


def test_every_corpus_file_chunks_without_error_and_yields_something():
    for path, text in load_corpus():
        chunks = chunk_markdown(text, path.name)
        assert chunks, f"{path.name} produced no chunks"
        assert all(c.text.strip() for c in chunks)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_chunking.py tests/ai/rag/test_corpus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.rag.chunking'`

- [ ] **Step 3: Implement chunking**

`backend/app/ai/rag/chunking.py`:

```python
"""Turning documents into retrievable pieces.

Two corpora, two strategies, and the difference is the point:

- Policy documents are structured markdown. Splitting on headers keeps each
  chunk inside one section and records the header path as metadata, so a hit
  can be cited as "Roads SOP › Response norms" rather than "chunk 17".
- Case records (resolved complaints, from Phase 2b onward) are short and
  self-contained. One record is one chunk; splitting them would only separate
  a description from its outcome.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_HEADER = re.compile(r"^(#{1,3})\s+(.*)$", re.M)


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    chunk_id: str
    metadata: dict = field(default_factory=dict)


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def _chunk_id(source: str, ordinal: int, text: str) -> str:
    digest = hashlib.sha1(f"{source}:{ordinal}:{text}".encode()).hexdigest()[:12]
    return f"{source}#{ordinal}-{digest}"


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """Recursive split by paragraph, then sentence, then hard cut, with overlap."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # prefer to break at a paragraph, then a sentence, then a space
            for sep in ("\n\n", ". ", " "):
                cut = text.rfind(sep, start, end)
                if cut > start + max_chars // 2:
                    end = cut + len(sep)
                    break
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in pieces if p]


def chunk_markdown(
    text: str, source: str, *, max_chars: int = 1800, overlap: int = 200
) -> list[Chunk]:
    front, body = _parse_front_matter(text)
    chunks: list[Chunk] = []
    header_path: list[str] = []
    ordinal = 0

    # Walk sections: each header starts a new section; text before any header is one.
    positions = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip()) for m in _HEADER.finditer(body)]
    boundaries = [(0, positions[0][0] if positions else len(body), None)]
    for i, (start, end, level, title) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        boundaries.append((end, nxt, (level, title)))

    for start, end, header in boundaries:
        if header:
            level, title = header
            header_path = header_path[: level - 1] + [title]
        section = body[start:end].strip()
        if not section:
            continue
        for piece in _split_long(section, max_chars, overlap):
            chunks.append(Chunk(
                text=piece,
                source=source,
                chunk_id=_chunk_id(source, ordinal, piece),
                metadata={**front, "headers": list(header_path)},
            ))
            ordinal += 1
    return chunks


def chunk_record(text: str, source: str, metadata: dict) -> list[Chunk]:
    """A case record is one chunk. Splitting it would separate cause from outcome."""
    return [Chunk(text=text, source=source, chunk_id=_chunk_id(source, 0, text),
                  metadata=dict(metadata))]


def load_corpus(directory: Path = CORPUS_DIR) -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.md"))]
```

- [ ] **Step 4: Author `sop_roads.md` as the template, run the chunking tests, then author the other fifteen**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_chunking.py -v` — expect 6 passing before any corpus exists.

Then write the corpus per the specification above. Run `tests/ai/rag/test_corpus.py` repeatedly; the department-name and SLA-agreement tests are the ones most likely to catch a drift between prose and code.

- [ ] **Step 5: Run the full suite and commit**

Expected: 256 + 6 + 8 = 270.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai/rag backend/tests/ai/rag
git commit -m "feat: author the municipal corpus and header-aware chunking

Twelve department SOPs, the SLA policy, a category taxonomy, a rate card and
the contractor scoring rationale — 16 documents that replace what v1 faked with
four hardcoded dictionaries.

Policy documents split on markdown headers so every chunk cites its section;
case records stay whole. Tests pin the corpus to the code: every SOP names its
seeded department verbatim, and the SLA policy states the same windows as
SLA_HOURS."
```

---

## Task 3: The FAISS store with a tag-checked sidecar

**Files:**
- Create: `backend/app/ai/rag/store.py`
- Test: `backend/tests/ai/rag/test_store.py`

**Interfaces:**
- `class FaissStore`:
  - `__init__(embedder: Embedder)`
  - `add(chunks: list[Chunk]) -> None` — embeds and indexes; keeps chunks as the metadata sidecar
  - `search(query: str, *, fetch_k: int = 50) -> list[tuple[Chunk, float]]` — cosine, descending
  - `save(directory: Path) -> None` — `index.faiss` + `chunks.json` + `manifest.json` (`model_tag`, `dim`, `count`)
  - `load(directory: Path, embedder: Embedder) -> FaissStore` (classmethod) — raises `IndexModelMismatch` if the manifest's tag differs from the embedder's
  - `__len__`
- `class IndexModelMismatch(RuntimeError)`

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/rag/test_store.py`:

```python
import pytest

from app.ai.rag.chunking import chunk_record
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.store import FaissStore, IndexModelMismatch


def _chunks():
    return [
        chunk_record("A deep pothole on the main road near the school gate", "c1", {"category": "ROADS"}),
        chunk_record("The streetlight on Church Street has been dark for a week", "c2", {"category": "ELECTRICITY"}),
        chunk_record("Sewage overflowing from an open manhole outside the clinic", "c3", {"category": "SEWAGE"}),
    ]


def test_search_returns_the_most_similar_chunk_first():
    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    # The fake embedder is content-seeded, so the exact text is its own nearest neighbour.
    hits = store.search("A deep pothole on the main road near the school gate", fetch_k=3)
    assert hits[0][0].source == "c1"
    assert hits[0][1] > hits[1][1]


def test_scores_are_cosine_similarities():
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    (chunk, score), = store.search("A deep pothole on the main road near the school gate", fetch_k=1)
    assert abs(score - 1.0) < 1e-5, "identical text should score ~1.0 under cosine"


def test_fetch_k_is_capped_at_the_index_size():
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    assert len(store.search("anything", fetch_k=50)) == 1


def test_empty_store_returns_nothing_rather_than_raising():
    assert FaissStore(FakeEmbedder()).search("anything") == []


def test_save_and_load_round_trip(tmp_path):
    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    store.save(tmp_path)

    loaded = FaissStore.load(tmp_path, FakeEmbedder())
    assert len(loaded) == 3
    hits = loaded.search("Sewage overflowing from an open manhole outside the clinic", fetch_k=1)
    assert hits[0][0].source == "c3"
    assert hits[0][0].metadata["category"] == "SEWAGE"


def test_loading_with_a_different_embedder_is_refused(tmp_path):
    """The whole reason the tag exists: silent dimension or model drift returns
    plausible-looking wrong neighbours. It must fail loudly instead."""
    store = FaissStore(FakeEmbedder())
    store.add(_chunks()[0])
    store.save(tmp_path)

    class OtherEmbedder(FakeEmbedder):
        model_tag = "other-model@768"

    with pytest.raises(IndexModelMismatch, match="fake@768"):
        FaissStore.load(tmp_path, OtherEmbedder())


def test_chunks_property_exposes_the_sidecar_in_index_order():
    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    assert [c.source for c in store.chunks] == ["c1", "c2", "c3"]


def test_manifest_records_what_was_indexed(tmp_path):
    import json

    store = FaissStore(FakeEmbedder())
    for group in _chunks():
        store.add(group)
    store.save(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest == {"model_tag": "fake@768", "dim": 768, "count": 3}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.rag.store'`

- [ ] **Step 3: Implement**

`backend/app/ai/rag/store.py`:

```python
"""FAISS behind a small, honest interface.

IndexFlatIP over unit vectors is cosine similarity, exact, with no training
step — right for a corpus of a few thousand chunks. FAISS stores vectors only,
so the chunks themselves live in a JSON sidecar in index order; position i in
the index is chunks[i].

The manifest stamps the embedding model tag. Loading an index with a different
embedder is refused: a mismatched model does not error, it returns plausible
wrong neighbours, which is the worst possible failure mode for retrieval.
"""

import json
from dataclasses import asdict
from pathlib import Path

import faiss
import numpy as np

from app.ai.rag.chunking import Chunk
from app.ai.rag.embeddings import EMBEDDING_DIM, Embedder


class IndexModelMismatch(RuntimeError):
    pass


class FaissStore:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
        self._chunks: list[Chunk] = []

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[Chunk]:
        """The sidecar, in index order. BM25 is built over the same list."""
        return self._chunks

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vectors = np.asarray(self._embedder.embed_documents([c.text for c in chunks]), dtype="float32")
        faiss.normalize_L2(vectors)
        self._index.add(vectors)
        self._chunks.extend(chunks)

    def search(self, query: str, *, fetch_k: int = 50) -> list[tuple[Chunk, float]]:
        if not self._chunks:
            return []
        vector = np.asarray([self._embedder.embed_query(query)], dtype="float32")
        faiss.normalize_L2(vector)
        k = min(fetch_k, len(self._chunks))
        scores, ids = self._index.search(vector, k)
        return [(self._chunks[i], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / "index.faiss"))
        (directory / "chunks.json").write_text(
            json.dumps([asdict(c) for c in self._chunks]), encoding="utf-8"
        )
        (directory / "manifest.json").write_text(json.dumps({
            "model_tag": self._embedder.model_tag,
            "dim": EMBEDDING_DIM,
            "count": len(self._chunks),
        }), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path, embedder: Embedder) -> "FaissStore":
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["model_tag"] != embedder.model_tag:
            raise IndexModelMismatch(
                f"index was built with {manifest['model_tag']!r} but the configured "
                f"embedder is {embedder.model_tag!r}; rebuild the index or switch embedder"
            )
        store = cls(embedder)
        store._index = faiss.read_index(str(directory / "index.faiss"))
        store._chunks = [Chunk(**c) for c in json.loads((directory / "chunks.json").read_text(encoding="utf-8"))]
        return store
```

- [ ] **Step 4: Run the tests and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_store.py -v` — 8 passing. Full suite: 278.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai/rag backend/tests/ai/rag
git commit -m "feat: add the FAISS store with a tag-checked manifest

IndexFlatIP over unit vectors is exact cosine similarity; chunks live in a JSON
sidecar in index order. The manifest stamps the embedding model tag and load()
refuses a mismatch — a wrong model does not error, it returns plausible wrong
neighbours, which is the worst failure mode retrieval can have."
```

---

## Task 4: Dense, BM25 and hybrid retrievers

**Files:**
- Create: `backend/app/ai/rag/retrievers.py`
- Test: `backend/tests/ai/rag/test_retrievers.py`

**Interfaces:**
- `@dataclass(frozen=True) Hit(chunk: Chunk, score: float, source_retriever: str)`
- `class DenseRetriever(store: FaissStore)`: `search(query, *, k=5, fetch_k=50, filters: dict | None = None) -> list[Hit]`
- `class BM25Retriever(chunks: list[Chunk])`: same signature
- `rrf_merge(rankings: list[list[Hit]], *, k: int = 60) -> list[Hit]` — Reciprocal Rank Fusion, `score = Σ 1/(k + rank)`
- `class HybridRetriever(dense: DenseRetriever, sparse: BM25Retriever)`: `search(query, *, k=5, fetch_k=50, filters=None) -> list[Hit]`
- `matches(chunk: Chunk, filters: dict | None) -> bool` — every filter key must equal the chunk's metadata value

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/rag/test_retrievers.py`:

```python
from app.ai.rag.chunking import chunk_record
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.retrievers import (
    BM25Retriever, DenseRetriever, Hit, HybridRetriever, matches, rrf_merge,
)
from app.ai.rag.store import FaissStore


def _corpus():
    rows = [
        ("c1", "A deep pothole on the main road near the school gate", "ROADS", "East"),
        ("c2", "Potholes along the highway shoulder after the monsoon", "ROADS", "West"),
        ("c3", "The streetlight on Church Street has been dark for a week", "ELECTRICITY", "East"),
        ("c4", "Sewage overflowing from an open manhole outside the clinic", "SEWAGE", "East"),
        ("c5", "Broken bench and fallen tree in the park", "PUBLIC_SPACES", "West"),
    ]
    return [chunk_record(t, s, {"category": c, "district": d})[0] for s, t, c, d in rows]


def _dense():
    store = FaissStore(FakeEmbedder())
    store.add(_corpus())
    return DenseRetriever(store)


def test_bm25_finds_lexical_matches_the_fake_embedder_cannot():
    """The fake embedder is content-hashed, so 'pothole' and 'potholes' are unrelated
    to it. BM25 tokenises, so the sparse side catches what dense misses. That is the
    argument for hybrid."""
    hits = BM25Retriever(_corpus()).search("pothole", k=2)
    assert {h.chunk.source for h in hits} == {"c1", "c2"}


def test_dense_returns_exact_text_as_top_hit():
    hits = _dense().search("A deep pothole on the main road near the school gate", k=1)
    assert hits[0].chunk.source == "c1"
    assert hits[0].source_retriever == "dense"


def test_metadata_filter_is_applied_after_fetch():
    """FAISS has no filtering; we over-fetch and filter in Python."""
    hits = _dense().search("pothole", k=5, fetch_k=50, filters={"district": "West"})
    assert hits and all(h.chunk.metadata["district"] == "West" for h in hits)


def test_filter_can_empty_the_result_without_raising():
    assert _dense().search("pothole", filters={"district": "Nowhere"}) == []


def test_matches_requires_every_filter_key():
    chunk = _corpus()[0]
    assert matches(chunk, None)
    assert matches(chunk, {"category": "ROADS"})
    assert matches(chunk, {"category": "ROADS", "district": "East"})
    assert not matches(chunk, {"category": "ROADS", "district": "West"})
    assert not matches(chunk, {"missing_key": "x"})


def test_rrf_rewards_appearing_in_both_rankings():
    a = Hit(_corpus()[0], 0.9, "dense")
    b = Hit(_corpus()[1], 0.8, "dense")
    c = Hit(_corpus()[2], 0.7, "dense")
    dense = [a, b, c]
    sparse = [Hit(_corpus()[1], 3.0, "bm25"), Hit(_corpus()[4], 2.0, "bm25")]

    merged = rrf_merge([dense, sparse], k=60)
    # c2 (index 1) is rank 2 in dense and rank 1 in sparse: 1/62 + 1/61 — beats c1's 1/61 alone
    assert merged[0].chunk.source == "c2"
    assert merged[0].source_retriever == "hybrid"
    assert abs(merged[0].score - (1 / 62 + 1 / 61)) < 1e-9


def test_rrf_deduplicates_by_chunk_id():
    hit = Hit(_corpus()[0], 1.0, "dense")
    merged = rrf_merge([[hit], [hit]])
    assert len(merged) == 1


def test_hybrid_beats_either_alone_on_a_lexical_plus_semantic_query():
    """Exact text finds c1 densely; 'potholes' finds c2 lexically; hybrid surfaces both."""
    hybrid = HybridRetriever(_dense(), BM25Retriever(_corpus()))
    hits = hybrid.search("A deep pothole on the main road near the school gate potholes", k=2)
    assert {h.chunk.source for h in hits} == {"c1", "c2"}


def test_hybrid_respects_filters_on_both_sides():
    hybrid = HybridRetriever(_dense(), BM25Retriever(_corpus()))
    hits = hybrid.search("pothole", k=5, filters={"district": "East"})
    assert hits and all(h.chunk.metadata["district"] == "East" for h in hits)


def test_hit_is_frozen():
    import dataclasses
    assert Hit.__dataclass_params__.frozen
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_retrievers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.rag.retrievers'`

- [ ] **Step 3: Implement**

`backend/app/ai/rag/retrievers.py`:

```python
"""Three ways to find a chunk, and how to combine them.

Dense retrieval matches meaning; BM25 matches words. Each misses what the other
catches — "potholes" is a different token from "pothole" to BM25 but the same
idea to an embedding, while a rare proper noun the embedding never learned is
trivial for BM25. Reciprocal Rank Fusion merges the two rankings without needing
their scores to be comparable, which they are not.

FAISS has no metadata filtering, so every retriever over-fetches `fetch_k`
candidates and filters in Python before taking `k`. Fine below ~10k chunks;
docs/adr/0002 records the tradeoff.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.ai.rag.chunking import Chunk
from app.ai.rag.store import FaissStore

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    source_retriever: str


def matches(chunk: Chunk, filters: dict | None) -> bool:
    if not filters:
        return True
    return all(chunk.metadata.get(key) == value for key, value in filters.items())


def _tokenise(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class DenseRetriever:
    def __init__(self, store: FaissStore) -> None:
        self._store = store

    def search(self, query: str, *, k: int = 5, fetch_k: int = 50, filters: dict | None = None) -> list[Hit]:
        candidates = self._store.search(query, fetch_k=fetch_k)
        hits = [Hit(c, s, "dense") for c, s in candidates if matches(c, filters)]
        return hits[:k]


class BM25Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._bm25 = BM25Okapi([_tokenise(c.text) for c in chunks]) if chunks else None

    def search(self, query: str, *, k: int = 5, fetch_k: int = 50, filters: dict | None = None) -> list[Hit]:
        if not self._bm25:
            return []
        scores = self._bm25.get_scores(_tokenise(query))
        ranked = sorted(range(len(self._chunks)), key=lambda i: scores[i], reverse=True)[:fetch_k]
        hits = [
            Hit(self._chunks[i], float(scores[i]), "bm25")
            for i in ranked
            if scores[i] > 0 and matches(self._chunks[i], filters)
        ]
        return hits[:k]


def rrf_merge(rankings: list[list[Hit]], *, k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion: score = Σ over rankings of 1 / (k + rank).

    Rank is 1-based. k=60 is the value from the original paper and damps the
    advantage of being first in any single list. Scores from the inputs are
    ignored on purpose — a cosine and a BM25 score are not comparable."""
    fused: dict[str, float] = defaultdict(float)
    by_id: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            fused[hit.chunk.chunk_id] += 1.0 / (k + rank)
            by_id.setdefault(hit.chunk.chunk_id, hit.chunk)
    return [
        Hit(by_id[cid], score, "hybrid")
        for cid, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    ]


class HybridRetriever:
    def __init__(self, dense: DenseRetriever, sparse: BM25Retriever) -> None:
        self._dense = dense
        self._sparse = sparse

    def search(self, query: str, *, k: int = 5, fetch_k: int = 50, filters: dict | None = None) -> list[Hit]:
        dense = self._dense.search(query, k=fetch_k, fetch_k=fetch_k, filters=filters)
        sparse = self._sparse.search(query, k=fetch_k, fetch_k=fetch_k, filters=filters)
        return rrf_merge([dense, sparse])[:k]
```

- [ ] **Step 4: Run the tests and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_retrievers.py -v` — 10 passing. Full suite: 288.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai/rag backend/tests/ai/rag
git commit -m "feat: add dense, BM25 and hybrid retrievers with RRF

Dense matches meaning, BM25 matches words, and each misses what the other
catches. Reciprocal Rank Fusion merges the rankings without pretending a cosine
and a BM25 score are comparable. FAISS cannot filter, so every retriever
over-fetches and filters in Python — the documented cost of the FAISS choice."
```

---

## Task 5: The ingest CLI, the documents table, and the ADR

**Files:**
- Create: `backend/app/ai/rag/ingest.py`, `docs/adr/0002-faiss-over-pgvector.md`
- Modify: `docs/superpowers/specs/2026-09-02-civicai-v2-design.md` (phase table)
- Test: `backend/tests/ai/rag/test_ingest.py`

**Interfaces:**
- `ingest_policy_corpus(*, embedder: Embedder, index_dir: Path, session_factory, corpus_dir: Path = CORPUS_DIR) -> IngestReport`
- `@dataclass IngestReport(documents: int, chunks: int, skipped_unchanged: int, index_dir: Path)`
- `load_policy_retriever(*, embedder: Embedder, index_dir: Path) -> HybridRetriever`
- CLI: `python -m app.ai.rag.ingest` (uses `build_embedder()`, `settings.rag_index_dir`, `SessionLocal`)
- Idempotent on `Document.content_hash`: an unchanged file is skipped; a changed one is re-indexed and its old chunk rows replaced

- [ ] **Step 1: Write the failing test**

`backend/tests/ai/rag/test_ingest.py`:

```python
from pathlib import Path

from app.ai.rag.chunking import CORPUS_DIR
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.ingest import IngestReport, ingest_policy_corpus, load_policy_retriever
from app.db.models.ai import Document, DocumentChunk


def _mini_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "sop_roads.md").write_text(
        "---\ntitle: Roads SOP\ncollection: policy\ncategory: ROADS\n---\n\n# Roads SOP\n\n"
        "## Scope\n\nPotholes and surface cracks on existing roads.\n\n"
        "## Response norms\n\nCritical within 4 hours.\n", encoding="utf-8")
    (corpus / "sla_policy.md").write_text(
        "---\ntitle: SLA\ncollection: policy\n---\n\n# SLA policy\n\n## Windows\n\n"
        "Critical 4 hours, high 24 hours, medium 72 hours, low 168 hours.\n", encoding="utf-8")
    return corpus


def test_ingest_indexes_every_file_and_records_it(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    report = ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                                  session_factory=lambda: db_session, corpus_dir=corpus)
    assert isinstance(report, IngestReport)
    assert report.documents == 2
    assert report.chunks >= 2
    assert (tmp_path / "idx" / "manifest.json").exists()

    docs = db_session.query(Document).all()
    assert {d.source_path for d in docs} == {"sop_roads.md", "sla_policy.md"}
    assert all(d.embedding_model == "fake@768" for d in docs)
    assert all(d.collection == "policy" for d in docs)
    assert db_session.query(DocumentChunk).count() == report.chunks


def test_ingest_is_idempotent_on_content(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    kwargs = dict(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                  session_factory=lambda: db_session, corpus_dir=corpus)
    ingest_policy_corpus(**kwargs)
    second = ingest_policy_corpus(**kwargs)
    assert second.skipped_unchanged == 2
    assert db_session.query(Document).count() == 2, "unchanged files must not duplicate rows"


def test_a_changed_file_is_reindexed_and_old_chunks_replaced(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    kwargs = dict(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                  session_factory=lambda: db_session, corpus_dir=corpus)
    first = ingest_policy_corpus(**kwargs)
    (corpus / "sop_roads.md").write_text(
        (corpus / "sop_roads.md").read_text() + "\n## Escalation\n\nWard then block then district.\n",
        encoding="utf-8")
    second = ingest_policy_corpus(**kwargs)

    assert second.skipped_unchanged == 1
    roads = db_session.query(Document).filter_by(source_path="sop_roads.md").one()
    assert db_session.query(DocumentChunk).filter_by(document_id=roads.id).count() > 0
    assert db_session.query(Document).count() == 2
    assert db_session.query(DocumentChunk).count() == second.chunks


def test_the_loaded_retriever_finds_a_policy_chunk_with_a_citation(db_session, tmp_path):
    corpus = _mini_corpus(tmp_path)
    ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                         session_factory=lambda: db_session, corpus_dir=corpus)
    retriever = load_policy_retriever(embedder=FakeEmbedder(), index_dir=tmp_path / "idx")
    hits = retriever.search("critical response window hours", k=2)
    assert hits
    top = hits[0].chunk
    assert top.source in {"sop_roads.md", "sla_policy.md"}
    assert top.metadata["headers"], "a policy hit must be citable by section"


def test_the_real_corpus_ingests_end_to_end(db_session, tmp_path):
    """The authored corpus, the chunker, the store and the DB rows all agree."""
    report = ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=tmp_path / "idx",
                                  session_factory=lambda: db_session, corpus_dir=CORPUS_DIR)
    assert report.documents == 16
    assert report.chunks >= 16
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/ai/rag/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.rag.ingest'`

- [ ] **Step 3: Implement**

`backend/app/ai/rag/ingest.py`:

```python
"""Build the policy index from the corpus, and record what was indexed.

Idempotent on content: a file whose hash matches its Document row is skipped, a
changed file is re-chunked and its old DocumentChunk rows replaced. The whole
FAISS index is rebuilt each run — with a few hundred chunks that costs seconds,
and it keeps the sidecar and the DB rows trivially consistent.

Run with: python -m app.ai.rag.ingest
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.ai.rag.chunking import CORPUS_DIR, Chunk, chunk_markdown, load_corpus
from app.ai.rag.embeddings import Embedder
from app.ai.rag.retrievers import BM25Retriever, DenseRetriever, HybridRetriever
from app.ai.rag.store import FaissStore
from app.db.base import utcnow

logger = logging.getLogger(__name__)

COLLECTION = "policy"


@dataclass
class IngestReport:
    documents: int
    chunks: int
    skipped_unchanged: int
    index_dir: Path


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_policy_corpus(
    *,
    embedder: Embedder,
    index_dir: Path,
    session_factory: Callable,
    corpus_dir: Path = CORPUS_DIR,
) -> IngestReport:
    from app.db.models.ai import Document, DocumentChunk

    session = session_factory()
    try:
        all_chunks: list[Chunk] = []
        skipped = 0

        for path, text in load_corpus(corpus_dir):
            digest = _content_hash(text)
            doc = session.query(Document).filter_by(
                collection=COLLECTION, source_path=path.name
            ).one_or_none()

            chunks = chunk_markdown(text, path.name)
            if doc is not None and doc.content_hash == digest and doc.embedding_model == embedder.model_tag:
                skipped += 1
                # still needs to be in the rebuilt index
                all_chunks.extend(chunks)
                continue

            if doc is None:
                doc = Document(collection=COLLECTION, source_path=path.name)
                session.add(doc)
                session.flush()
            else:
                session.query(DocumentChunk).filter_by(document_id=doc.id).delete()

            doc.title = chunks[0].metadata.get("title") if chunks else None
            doc.content_hash = digest
            doc.chunk_count = len(chunks)
            doc.embedding_model = embedder.model_tag
            doc.indexed_at = utcnow()
            for seq, chunk in enumerate(chunks):
                session.add(DocumentChunk(
                    document_id=doc.id, seq=seq, text=chunk.text,
                    metadata_json={**chunk.metadata, "chunk_id": chunk.chunk_id},
                ))
            all_chunks.extend(chunks)

        session.commit()

        store = FaissStore(embedder)
        store.add(all_chunks)
        store.save(index_dir)

        documents = session.query(Document).filter_by(collection=COLLECTION).count()
        logger.info("indexed %d documents, %d chunks (%d unchanged) into %s",
                    documents, len(all_chunks), skipped, index_dir)
        return IngestReport(documents=documents, chunks=len(all_chunks),
                            skipped_unchanged=skipped, index_dir=index_dir)
    finally:
        session.close()


def load_policy_retriever(*, embedder: Embedder, index_dir: Path) -> HybridRetriever:
    store = FaissStore.load(index_dir, embedder)
    return HybridRetriever(DenseRetriever(store), BM25Retriever(store.chunks))


def main() -> None:
    from app.ai.rag.embeddings import build_embedder
    from app.config import settings
    from app.db.session import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = ingest_policy_corpus(
        embedder=build_embedder(),
        index_dir=Path(settings.rag_index_dir),
        session_factory=SessionLocal,
    )
    print(f"{report.documents} documents, {report.chunks} chunks -> {report.index_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the ADR**

`docs/adr/0002-faiss-over-pgvector.md`:

```markdown
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
  is why `Document.content_hash` skips the DB write but not the embed.
- **No concurrent writers.** One process rebuilds the index; readers load it.

## When to revisit

The moment case records (Phase 2b) push the corpus past ~10k chunks, or the
moment a second writer is needed. The `FaissStore` interface is small enough
that a `PgVectorStore` with the same `add`/`search`/`save`/`load` shape is a
contained change.
```

- [ ] **Step 5: Settle the Phase 1 doc inconsistency**

The spec's phase table and the Phase 1b plan both list LangSmith tracing and the SLA monitor port under Phase 1, and neither landed. Decide and record: edit the spec's §10 table so Phase 1's row reads "Graph core, API, streaming" and add an explicit row note that **LangSmith tracing moves to Phase 3 (evals & observability) and the SLA monitor port to Phase 2b (background workflows)**. An omission that is a decision is fine; one that is an accident is not.

- [ ] **Step 6: Run the full suite, try the CLI, and commit**

Run: `cd backend && .venv/bin/python -m pytest` — expect 293.

Then the CLI against the fake embedder, to see it work end to end without a key:

```bash
cd backend
rm -rf /tmp/civicai_idx
DATABASE_URL="sqlite:////tmp/civicai_ingest.db" .venv/bin/python -m alembic upgrade head >/dev/null
DATABASE_URL="sqlite:////tmp/civicai_ingest.db" .venv/bin/python -c "
from pathlib import Path
from app.ai.rag.embeddings import FakeEmbedder
from app.ai.rag.ingest import ingest_policy_corpus, load_policy_retriever
from app.db.session import SessionLocal
r = ingest_policy_corpus(embedder=FakeEmbedder(), index_dir=Path('/tmp/civicai_idx'), session_factory=SessionLocal)
print(r)
ret = load_policy_retriever(embedder=FakeEmbedder(), index_dir=Path('/tmp/civicai_idx'))
for h in ret.search('what is the response window for a critical pothole', k=3):
    print(f'  {h.score:.4f}  {h.chunk.source}  {\" › \".join(h.chunk.metadata[\"headers\"])}')
"
rm -rf /tmp/civicai_idx /tmp/civicai_ingest.db
```

Expected: 16 documents, a few dozen chunks, and three cited hits.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/ai/rag backend/tests/ai/rag docs/adr docs/superpowers/specs
git commit -m "feat: add the ingest CLI, document registry, and the FAISS ADR

python -m app.ai.rag.ingest chunks the corpus, embeds it, builds the index and
records every document and chunk in the tables Phase 0 built for it. Idempotent
on content hash. The ADR records what FAISS costs — no metadata filtering, two
stores to keep consistent — and when to revisit.

Also settles a doc inconsistency: LangSmith tracing moves to Phase 3 and the
SLA monitor port to Phase 2b, recorded in the spec's phase table."
```

---

## Phase 2a Done When

- [ ] `cd backend && .venv/bin/python -m pytest` passes — 293 tests, no network, no key, nothing written into the repository
- [ ] `python -m app.ai.rag.ingest` (with a key) or the fake-embedder snippet above builds an index of all 16 corpus documents and returns cited hits
- [ ] `FaissStore.load` refuses an index built with a different embedding model tag
- [ ] The corpus agrees with the code: every SOP names its seeded department verbatim and the SLA policy states the same windows as `SLA_HOURS` — both enforced by tests
- [ ] `docs/adr/0002` exists and the spec's phase table no longer claims Phase 1 delivered tracing or the SLA monitor

**Next:** Phase 2b — wire retrieval into `investigate`, `assess_risk`, `route` and `work_order`; citations into `state["evidence"]` and the `retrieved_chunks` table; delete the placeholder cost dict; the semantic cache; the SLA monitor port.

---

## Carried forward from Phase 2a (recorded 2026-09-15)

Phase 2a landed in ten commits (c2a1753..3f9ccaf), 308 tests, no network in the
suite. Every task was reviewed in isolation and the phase reviewed as a whole; the
items below were found and consciously deferred. Phase 2b should read this before
touching retrieval.

**What Phase 2b must do at the seam**
- Store citations against `DocumentChunk.id` (the UUID primary key), not only the
  derived `chunk_id`. Chunk ids are now content-stable (source + header path + text)
  so they survive edits elsewhere in a file, but a chunk whose own text changes gets
  a new id by design; the DB row id is the durable join key for `RetrievedChunk`.
- Use one index directory per collection: `collection_index_dir(settings.rag_index_path,
  "policy")` today, `.../"cases"` for resolved complaints. `FaissStore.save` overwrites
  the directory it is given; a whole rebuild into a shared directory wipes the other
  collection. A retriever that needs both queries two stores and RRF-merges.
- Filter with `doc_type`, not only `category`. The rate card, SLA policy, taxonomy
  and contractor-scoring documents carry no `category`, so `work_order` and `route`
  need `{"doc_type": "rate_card"}` / `{"doc_type": "contractor_scoring"}` (or two
  retrieval calls) to reach the documents they must cite.
- Scale `fetch_k`. Filtering happens after the dense top-`fetch_k` truncation; at 88
  chunks the default 50 already returned 3 of 5 STRAY_ANIMALS chunks under the fake
  embedder. Pass `fetch_k` proportional to corpus size (or the whole index for a
  narrow filter) until per-collection sharding makes filter-then-search possible.
- Wire loading into the API process: `main.py` has no RAG reference. Decide eager
  load in `lifespan` (with a clear message when the index does not exist yet) versus
  lazy `load_policy_retriever` inside nodes; handle `NoEmbedderConfigured`,
  `IndexModelMismatch` and `IndexCorrupt` explicitly rather than through a request.
- Retrievers are synchronous. `FaissStore.search` was probed with 8 threads × 200
  searches on the real corpus with no crash or mismatch, so `asyncio.to_thread` from
  async nodes is safe for reads. No concurrent `add`/`save` while serving — case-record
  ingest must not run alongside live queries in the same process.
- Add a DB index (or a generated column) for `metadata_json.chunk_id` on
  `document_chunks` once case records push the table past a few thousand rows.

**Chunking**
- `#` lines inside fenced code blocks parse as headers. No corpus file has a fence;
  guard `_HEADER` if one is ever added.
- `Chunk.metadata` is a shallow copy; nested mutables in caller-supplied metadata are
  shared by reference.
- Plural stripping handles `+s` only: `classes` → `classe`, not `clas`. All 128
  stripped-form collisions in the current vocabulary are intended singular/plural pairs.
- Prose overlap can shrink to under one wrapped line when the overlap window contains
  a newline (the line-boundary snap that keeps table rows whole).

**Store and ingest**
- `Chunk(**c)` on load is not forward-compatible with extra sidecar keys.
- `save` writes three files without temp-and-rename; a crash mid-save leaves a
  directory `load` will refuse (`IndexCorrupt`), which is the intended detection.
- The dimension check compares the manifest to `EMBEDDING_DIM`, not to the vector
  width read from `index.faiss`.
- Unchanged files still re-embed on every run (the index is rebuilt whole). Fine at
  88 chunks with a free embedder; an embedding cache keyed on `chunk_id` is the fix
  if case records make it slow.
- `session_factory: Callable` should read `Callable[[], Session]`.

**Corpus**
- SOP sections run 80–150 words, under the plan's 250–400 target, by choice: every
  section is specific, and the tests pin the numbers that matter. Extend a section
  only with real detail.
- "Hybrid beats either retriever alone" is a Phase 3 eval question; the fake embedder
  is content-hashed and cannot demonstrate it.

**Doc inconsistency settled**
- LangSmith tracing → Phase 3; SLA monitor port → Phase 2b. Recorded in the spec's
  phase table.
