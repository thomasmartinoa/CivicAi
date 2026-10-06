# Spec success criteria — verified 2026-10-06

The design spec (§11) lists seven. This is each one checked against a running system
rather than against the code that is supposed to implement it.

| # | Criterion | Verdict |
|---|---|---|
| 1 | A complaint completes the pipeline and the run is inspectable in a trace viewer | ✅ in-app; ⚠️ LangSmith wired but unverified |
| 2 | A failed run resumes from its checkpoint | ✅ verified, and it took two fixes |
| 3 | Costs, SLA windows and routing derive from retrieved documents; no hardcoded dicts | ✅ |
| 4 | `python -m app.evals.run` produces a report with all three columns | ✅ |
| 5 | The three scheduled jobs run and produce real output | ✅ all three, live |
| 6 | `pytest` passes with no network access | ✅ verified in a network namespace |
| 7 | Eleven documents exist, referencing real code | ✅ |
| — | `docker compose up` produces a working system | ✅ verified; seven defects found |

---

## 5 — the scheduled jobs, run live

These had **never been run outside a unit test**: every server in development was
started with `BACKGROUND_JOBS_ENABLED=false`, so the dev database held zero briefings
and zero escalations. Running them is what this section is.

### SLA monitor

```
SlaTick(warned=0, urgent=0, breached=1)
```

It caught `CIV-ZW363V9T` — a gas-cylinder leak with a four-hour SLA, 3.27 windows
elapsed — and wrote one `escalations` row: *"SLA breached on work order fc9dc60a…"*.
The notification carries a dedupe key, so a second tick does not email twice. The SMTP
relay was absent and the send failed; the job logged it and completed, which is the
intended best-effort behaviour.

### Daily briefing

`is_fallback: False` — real narrative, not the template. v1 served template text for
the life of the project without anyone noticing, which is why that flag exists.

> Today is relatively quiet with only two new complaints and no resolved cases.
> However, we have one active escalation and one severely overdue work order.
>
> - Address the critical backlog on work order CIV-ZW363V9T, which has reached 327%
>   of its window.
> - Resolve the outstanding escalated issue.
> - Review the single work order that has progressed past half its scheduled window.

Counts: 2 new, 0 resolved, 1 at risk, 1 escalation — each matching the database. The
**327%** matches the measured elapsed fraction of 3.27 exactly, so the narrative is
reading the real number rather than paraphrasing a vague one.

### Cluster detection

First attempt: `ClusterTick(clusters=0, complaints=0)` on two near-identical pothole
reports **31 metres apart**. Not a bug — `cluster_min_size = 3`. Grouping two
complaints into one work order on the strength of a pair is a weaker signal than
three, and the test was under-specified rather than the code wrong.

With a third:

```
ClusterTick(clusters=1, complaints=3)
  CIV-ZQD8KJO2: cluster=aca2fee4-528
  CIV-MFQ34CCN: cluster=aca2fee4-528
  CIV-35X423DF: cluster=aca2fee4-528
  GROUPED ORDER: size=3  sla=4h  crew=RoadFix India Pvt Ltd
```

Three separately-submitted complaints, independently classified `ROADS`, collapsed into
one work order for one crew.

The grouped order's cost came back `None` with the basis *"estimate unavailable: no
cost chain configured"*, because this invocation passed no cost chain — the scheduler
does. That is ADR 0006 working: no chain, so no number, rather than a zero.

---

## 6 — no network, checked rather than assumed

The suite has no socket guard, so "passes with no network" had only ever meant "no test
happens to make a call". Run inside an empty network namespace it is now a statement
about the suite rather than about the machine:

```bash
unshare -r -n .venv/bin/python -m pytest -q
# 904 passed in 18.39s
```

---

## 1 — the caveat

The **in-app** trace viewer is verified: `/admin/runs` renders every pipeline run and
every chat turn with its step timeline, and the screenshot in `docs/screenshots/`
shows a real failure and its retry.

**LangSmith is wired and unverified.** `app/ai/observability.py` has the `@traced`
decorator and run metadata, and `.env.example` documents the variables, but no run in
this project has been inspected in LangSmith — there has never been a key configured.
The criterion says "inspectable in both"; only one of the two has been checked.


---

## Deployment — verified the same way

The compose stack was reviewed before it could be run, and **five defects** were found
by reading it against the application's requirements. Each would have stopped it
starting: a placeholder `SECRET_KEY` against a guard that refuses to boot, a
`postgresql://` URL with no driver in `requirements.txt`, no migration step, Python
3.12 against a 3.14 project, and no `GEMINI_API_KEY` passed.

Then it was actually run, and found **two more**:

- **No `.dockerignore` anywhere.** The backend build context was 326 MB, of which 319
  MB was the host `.venv` — Linux wheels built against the host's Python, sent on every
  build and then copied into `/app` *after* `pip install`, shadowing the packages just
  installed. Context after the fix: **1.2 MB**.
- **No way to create a first tenant.** Seeding was only reachable through
  `POST /admin/seed`, which is gated on `ENVIRONMENT == "development"` — correct for an
  unauthenticated writer, and compose runs as production. A fresh stack came up
  *healthy* with no tenant and no admin user: login failed because the account did not
  exist, and a complaint failed with "tenant is ambiguous". `python -m app.services.seed`
  now runs between the migration and the server.

Verified end to end:

```
civicai-backend-1    Up (healthy)   0.0.0.0:8000->8000/tcp
civicai-frontend-1   Up             0.0.0.0:3000->80/tcp

6 migrations applied · "seed: Database seeded successfully"
POST /complaints/ → CIV-084IBGH9 → assigned, ELECTRICITY, medium
/admin/corpus → 16 documents, 100 chunks, gemini-embedding-001@768
```

The index is the one step that is not automatic, because it needs the embedding API
and cannot run at build time. Until it runs the system says so in the startup log, on
`/admin/corpus` and on every evidence panel, and processes complaints without
citations rather than refusing to start — ADR 0003 behaving as designed in a
deployment rather than in a test.

**Five of the seven defects were found by reading and two by running.** The reading
was worth doing and was not sufficient, which is the same lesson as `docs/07` §5: all
six application-level production bugs in this project also came from running it.
