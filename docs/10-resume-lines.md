# 10 — Resume lines

Claims, and the evidence for each. Every number can be reproduced from this repository;
where a figure is caveated, the caveat is part of the line.

---

## The lines

**Built an AI complaint-resolution pipeline on LangGraph — 9 nodes with conditional
branching, a bounded re-classification loop and per-file fan-out — processing citizen
reports end to end with checkpointed resumption.**
→ `app/ai/graph/`, `GRAPH_VERSION = "2b.0"`. Verified live: a complaint submitted over
HTTP was classified `ELECTRICITY` at 0.99 confidence, geocoded, routed with 8
citations and a 72-hour SLA.

**Grounded every AI decision in a retrieval corpus and measured what it was worth:
macro-F1 0.81 → 0.93 against an ungrounded control on a 100-item golden set.**
→ `docs/eval-reports/2026-10-04.md`. The control column is the same prompts with
retrievers set to `None`, kept registered for exactly this comparison. Accuracy rose
~5 points while macro-F1 rose 12, so the gain is concentrated in rare categories.
*Caveat: this baseline is stale as of 2026-10-06 — it was measured under the previous
validator.*

**Designed an evaluation harness that refuses to overstate a result** — it reports
`None` rather than `0.0` for an unmeasured metric, carries the `n` behind every figure,
and declines to call a prompt change an improvement when it moves two error types in
opposite directions.
→ `app/evals/metrics.py`, `report.py`, `prompt_ab.py`. The rule caught **four reporting
bugs in the project's own tooling**.

**Made an LLM agent's tenant isolation structural rather than prompt-based:** no tool
accepts a tenant parameter, so there is nothing for a model to fill with another
department's id.
→ `app/ai/tools/officer.py`; enforced by an AST-walking test. Justified by measurement
— 1 in 6 prompt-injection items in the golden set still moves its risk band, so
citizen text demonstrably steers the model.

**Found and fixed six production defects that a 900-test suite could not see**,
including a transient 503 that permanently abandoned a classified fire-hazard
complaint, and a resume that replayed the failed node's cached error instead of
retrying it.
→ `docs/04` §5, with the three `AgentRun` rows showing a 20 ms "retry" that made no
model call.

**Diagnosed a self-amplifying rate-limit failure** where the provider client's own
retries bypassed the application's rate limiter, turning every 429 into more traffic;
after the fix the same sweep ran 80 calls with zero rejections.
→ `app/ai/llm.py`, `docs/06` §3.

**Shipped six React screens, each verified by rendering it in a headless browser
rather than by type-checking** — which found five defects `tsc` and curl both missed,
including a detail screen reading a field the API has never sent that hid four phases
of grounding work behind a passing type check.
→ `docs/screenshots/`, Phase 5 carried-forward.

**Wrote a multi-tenant FastAPI surface with structural safeguards**: another tenant's
record is 404 rather than 403, a citizen's one-time code is hashed, single-use,
expiring and attempt-limited, and the public dashboard is built by exclusion with
coordinates coarsened to ~110 m before grouping.
→ `app/api/`, `app/services/otp.py`, `app/schemas/public.py`.

---

## Numbers, with their sources

| Claim | Figure | Source |
|---|---|---|
| Tests | 904, no network, ~20s | `pytest -q` |
| Backend size | ~12k lines, 94 modules | `find app -name '*.py'` |
| API surface | 31 routes, 18 tables, 6 migrations | `app/main.py`, `alembic/versions/` |
| Retrieval gain | +0.12 macro-F1 | `docs/eval-reports/2026-10-04.md` |
| Validator trade | 9 → 3 wrong rejections per 40, +1 junk | `docs/eval-reports/2026-10-06-…` |
| Corpus | 16 documents, 100 chunks | `/admin/corpus` |
| Free-tier limits | 15 req/min, 500/day flash-lite; 20/day strong | measured |

---

## What not to claim

- **Not** "99% accurate". Macro-F1 is 0.93 on a 100-item set that I wrote, and it is
  currently stale.
- **Not** "prompt-injection resistant". One live attempt was refused; 1 in 6 golden-set
  items still moves a risk band.
- **Not** "production-ready". There is no retention policy, no frontend test suite, and
  three citizen endpoints are unbuilt.
- **Not** "fully autonomous". The agent is read-only by design, because approval
  tooling does not exist yet.

The strongest thing to say about this project is not a score. It is that **every one of
those limitations is written down in the repository**, each phase plan ends with what
it deferred, and the dashboard tells an officer when its own headline number cannot be
trusted.
