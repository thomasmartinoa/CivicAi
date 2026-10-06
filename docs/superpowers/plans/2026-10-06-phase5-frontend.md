# Phase 5 — the six screens

**Status:** planned 2026-10-06, after Phase 4b (`c31b606`), 867 backend tests.

The spec names six screens (§8). Eight screens already exist from v1 and were dragged
onto the v2 API in Phase 4a; this phase adds what the backend built in phases 1–4b and
nothing of it can currently be seen.

## The rule this phase is built around

**A screen is not done until it has been rendered and looked at.** Phase 4a verified
the officer screens by type-checking plus curl against every field, and that was
enough to find four contract bugs and not enough to know whether anything *looked*
right. Chromium headless is available here, so every screen in this phase gets a
screenshot committed under `docs/screenshots/`, taken against a real backend with real
data. A green `tsc` is not evidence.

Two corollaries from Phase 4b's carried-forward section, which are frontend problems:

- **`hit_step_limit` must not look like an answer.** The agent surrenders with a
  sentence; rendered as an ordinary bubble, a surrender reads as a conclusion.
- **Model-generated text must be escaped.** The `tool_call` event echoes the model's
  own arguments, and those can carry text a member of the public wrote into a
  complaint. React escapes by default; the rule is that nothing here reaches
  `dangerouslySetInnerHTML`, and a test asserts it.

## Order, and why

Chat first. It has the hardest contract — events arriving over time, a step limit that
must look different from an answer, tool calls that must appear *before* the result —
so it proves the SSE endpoint end to end in a way curl cannot. The read-only screens
after it are variations on fetch-and-render.

| # | Screen | Reads | Why it is in this position |
|---|---|---|---|
| 1 | **Officer chat** | `POST /admin/chat` (SSE) | Hardest contract; proves the streaming surface. |
| 2 | **Agent trace viewer** | `agent_steps` via a new endpoint | The transcript Phase 4b writes is currently invisible, and so is every pipeline run's step timeline. |
| 3 | **Evidence panel** | `AdminComplaintDetail.evidence` | The citations exist on the detail endpoint and nothing renders them. This is the Phase 2b grounding work finally becoming visible. |
| 4 | **Live pipeline view** | the complaint WebSocket | Replaces the dead "submitted" state the spec complains about. |
| 5 | **Knowledge base admin** | a new corpus endpoint | Needs a backend endpoint that does not exist; smallest new surface. |
| 6 | **Eval dashboard** | `docs/eval-reports/` data via a new endpoint | Last because the eval harness is a developer tool and the data is static between sweeps. |

## Backend work this phase needs

Three endpoints that do not exist. Each is small, officer-authenticated, and
tenant-scoped like everything in Phase 4a:

- `GET /admin/runs?complaint_id=` and `GET /admin/runs/{id}` — `agent_runs` with their
  `agent_steps`. Must distinguish a chat run (`complaint_id IS NULL`) from a pipeline
  run, and must surface `status == "step_limit"` so the trace viewer can show a
  surrender as a surrender.
- `GET /admin/corpus` — documents, chunk counts, the index manifest, when it was last
  built. Read-only; a reindex trigger is a mutation and needs the same argument
  mutation tools did, so it is **not** in this phase.
- `GET /admin/evals` — the latest baseline and report data. Reads what the harness
  already writes; computes nothing new, per the rule that nothing outside
  `services/` and `evals/` produces a number.

## Tasks

1. `GET /admin/runs` + the trace viewer screen.
2. The officer chat screen, SSE client, and the step-limit treatment.
3. The evidence panel on the complaint detail screen.
4. The live pipeline view over the existing WebSocket.
5. `GET /admin/corpus` + the knowledge base screen.
6. `GET /admin/evals` + the eval dashboard.
7. Screenshots of all six against a live backend, committed, plus a README that shows
   them.

Each task: backend endpoint with tests first where one is needed, then the screen,
then `npm run build`, then a screenshot looked at before the commit.

## What this phase will NOT do

- **No reindex button, no mutation from the knowledge base screen.** Rebuilding an
  index is a destructive operation on the thing every grounded answer depends on, and
  there is no confirmation mechanism in this codebase yet.
- **No new citizen screens.** The three deferred citizen endpoints — rating, fix
  verification, completion photo — are listed in Phase 4a's carried-forward section
  and belong together with their own backend work, which is Phase 6 or later.
- **No design system.** The existing Tailwind vocabulary is adequate and consistent;
  rewriting it would bury the actual work in a restyle.

## Carried forward

Filled in when the phase lands.
