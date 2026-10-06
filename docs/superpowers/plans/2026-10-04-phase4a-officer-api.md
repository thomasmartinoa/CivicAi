# Phase 4a — Officer Authentication and the API the Frontend Already Expects

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The React app in `frontend/` runs against this backend. An officer logs in,
sees the complaints, the work orders and the analytics, reads the morning briefing,
and approves a department email. A citizen checks their past complaints by email and
OTP. Nothing in this phase calls a model.

**Why this comes before the spec's Phase 4.** The spec orders Phase 4 (officer ReAct
agent, tools, SSE) before Phase 5 (six frontend screens). Two facts argue for
inserting this phase first:

1. **The frontend calls twelve endpoints and five exist.** `/admin/login`,
   `/admin/complaints`, `/admin/work-orders`, `/admin/analytics`,
   `/admin/analytics/performance`, `/admin/contractors`, `/admin/briefing`,
   `/public/dashboard`, `/complaints/verify-email` and `/complaints/verify-otp` are
   all missing. Until they exist there is no way to *look* at any of the work from
   phases 0–3, which is a real cost: a reviewer cannot see a pipeline they cannot run.
2. **This phase needs no model quota; the ReAct agent needs a lot.** The free tier
   allows 500 generate requests a day and a single eval sweep spends them. Auth,
   queries and aggregation are deterministic SQL and HTTP, so they can be built and
   tested without touching the provider at all.

The ReAct agent remains Phase 4b and is the better thing to build *onto* a working
officer surface than *instead* of one.

**Architecture:** A new `app/api/admin.py` and `app/api/public.py` alongside the
existing `complaints.py`, plus `app/services/auth.py` for password verification, JWT
issuing and the `get_current_officer` dependency. Officer endpoints are read-mostly
aggregation over the models Phase 0 built; the one write is approving an email draft,
which closes the deferral recorded in the Phase 2c plan. `app/api/` keeps talking to
the graph only through `ai.graph.runner`, as `tests/test_import_rules.py` enforces.

**Tech Stack:** FastAPI, `python-jose` or `pyjwt` (pick one and pin it), direct
`bcrypt` — not passlib, which does not work on Python 3.14 and is why `seed.py`
already calls bcrypt directly. SQLAlchemy 2. No new AI dependencies.

**Prior phases:** 0–3, **647 tests green, no network, no key**. Read the carried-forward
sections of the Phase 2c and Phase 3 plans first: Phase 2c deferred the officer
email-draft HTTP surface to "when officer auth exists", which is this phase, and
Phase 3 recorded that `validate` over-rejects, which the admin complaint list will
make visible to a human for the first time.

## Global Constraints

- Python 3.14, `backend/.venv`. `cd backend && .venv/bin/python -m pytest -q` starts
  at **647 passing** and every task keeps it green.
- **No model calls anywhere in this phase.** If a task seems to need one, it belongs
  in 4b.
- **Officer endpoints are authenticated; the public dashboard and the citizen OTP
  flow are not.** Every authenticated route is covered by a test that calls it
  *without* a token and expects 401, and one that calls it with a citizen's token and
  expects 403. A route added without those two tests is not finished.
- **Every query is tenant-scoped.** An officer sees their own tenant's complaints and
  nobody else's, and there is a test with two tenants for every list endpoint. This
  is the rule `route_node` already fails closed on, and the carried-forward lists
  record two places that still get it wrong.
- **No PII in tokens or logs.** The JWT carries the user id and role, not the email.
- **No N+1 queries in a list endpoint.** Use `selectinload` for the relationships the
  response needs, and assert the query count in a test for the complaint list.
- **Pagination is required, not optional**, on every list endpoint: a tenant with
  10,000 complaints must not be able to ask for all of them.
- Commit messages: imperative subject, body explains why. **No trailers of any kind.**
- A docstring on every module saying what it is for and what was rejected.

---

## File structure

| File | Responsibility |
|---|---|
| `backend/app/services/auth.py` (create) | `verify_password`, `create_access_token`, `decode_token` |
| `backend/app/api/deps.py` (create) | `get_current_user`, `get_current_officer`, `get_current_admin` |
| `backend/app/api/admin.py` (create) | login, me, complaints, work orders, contractors, analytics, briefing, email draft |
| `backend/app/api/public.py` (create) | the unauthenticated dashboard |
| `backend/app/api/complaints.py` (modify) | `verify-email`, `verify-otp` |
| `backend/app/db/models/core.py` + migration | `User.otp_code`, `User.otp_expires_at` — or a separate `CitizenOtp` table, decided in Task 6 |
| `backend/app/schemas/admin.py`, `public.py` (create) | response models, so the frontend has a contract |
| `backend/app/main.py` (modify) | mount the two new routers |
| `frontend/src/services/api.ts` (modify, Task 9) | whatever the real contract turns out to differ on |

---

### Task 1: Password verification and tokens

**Files:** create `app/services/auth.py`; test `tests/services/test_auth.py`

**Interfaces:**
- `verify_password(plain: str, hashed: str) -> bool` — direct bcrypt, never passlib
- `create_access_token(*, user_id: str, role: str, expires_delta: timedelta | None = None) -> str`
- `decode_token(token: str) -> TokenClaims` raising `InvalidToken` on anything wrong
- `@dataclass TokenClaims(user_id: str, role: str, expires_at: datetime)`

The tests that matter are the negative ones:

```python
def test_a_token_signed_with_another_secret_is_refused(monkeypatch):
    token = create_access_token(user_id="u-1", role="officer")
    monkeypatch.setattr(settings, "secret_key", "a-different-secret")
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_an_expired_token_is_refused():
    token = create_access_token(user_id="u-1", role="officer",
                                expires_delta=timedelta(seconds=-1))
    with pytest.raises(InvalidToken, match="expired"):
        decode_token(token)


def test_a_token_carries_no_email_or_name():
    """It goes into browser storage and into logs."""
    import base64, json
    payload = json.loads(base64.urlsafe_b64decode(
        create_access_token(user_id="u-1", role="officer").split(".")[1] + "=="))
    assert set(payload) <= {"sub", "role", "exp", "iat"}


def test_the_algorithm_is_pinned_and_none_is_refused():
    """alg=none is the classic JWT forgery; decode must not accept it."""
    ...


def test_a_wrong_password_is_refused_and_an_empty_hash_does_not_crash():
    """User.password_hash is nullable: a citizen row has none, and verifying
    against None must be False rather than an exception."""
    assert verify_password("x", None) is False
```

- [ ] Steps 1–5 as usual. Expect **+8 tests**. Commit: `feat: verify passwords and issue officer tokens`.

---

### Task 2: The dependencies, and what they refuse

**Files:** create `app/api/deps.py`; test `tests/api/test_auth_deps.py`

- `get_current_user` — decodes the bearer token, loads the `User`, 401 on anything wrong
- `get_current_officer` — 403 unless `role in ("officer", "admin")`
- `get_current_admin` — 403 unless `role == "admin"`

```python
def test_no_token_is_401_not_403(client):
    """401 means "who are you", 403 means "not allowed". A frontend that cannot
    tell them apart cannot decide whether to redirect to login."""
    assert client.get("/admin/complaints").status_code == 401


def test_a_citizen_token_on_an_officer_route_is_403(client, citizen_token): ...
def test_an_officer_token_on_an_admin_route_is_403(client, officer_token): ...
def test_a_token_for_a_deleted_user_is_401(client): ...
def test_a_malformed_authorization_header_is_401_not_500(client): ...
```

- [ ] Expect **+7 tests**. Commit: `feat: add the officer and admin route dependencies`.

---

### Task 3: Login, and the complaint list the officer actually needs

**Files:** create `app/api/admin.py`, `app/schemas/admin.py`; modify `app/main.py`;
test `tests/api/test_admin_auth.py`, `tests/api/test_admin_complaints.py`

- `POST /admin/login` — `{email, password}` → `{access_token, token_type, user: {...}}`.
  **The same message and the same timing for an unknown email and a wrong password**,
  so the endpoint is not an account-existence oracle.
- `GET /admin/me` — who the token belongs to, for the frontend's session restore.
- `GET /admin/complaints` — `?status=&category=&risk_level=&district=&q=&page=&size=`
  returning `{items, total, page, size}`. Ordered by `priority_score desc,
  created_at desc`: an officer opens this to find what to do next.
- `GET /admin/complaints/{id}` — one complaint with its media, work order,
  escalations, **evidence with citations** and `routing_justification`. This is the
  first screen on which the grounding work from Phase 2b is visible to a human.

```python
def test_an_unknown_email_and_a_wrong_password_are_indistinguishable(client):
    a = client.post("/admin/login", json={"email": "nobody@civicai.gov", "password": "x"})
    b = client.post("/admin/login", json={"email": "admin@civicai.gov", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_an_officer_sees_only_their_own_tenants_complaints(client, two_tenants): ...
def test_the_list_is_ordered_by_priority_then_recency(client): ...
def test_size_is_capped_so_a_client_cannot_ask_for_everything(client): ...
def test_the_detail_includes_the_evidence_citations(client): ...
def test_the_list_does_not_issue_a_query_per_complaint(client): ...
```

- [ ] Expect **+14 tests**. Commit: `feat: officer login and the complaint queue`.

---

### Task 4: Work orders, contractors, analytics

**Files:** modify `app/api/admin.py`, `app/schemas/admin.py`; test `tests/api/test_admin_operations.py`

- `GET /admin/work-orders` — `?status=`, paginated, with the complaint's tracking id,
  the contractor name, `sla_deadline` and **a computed `sla_state`** of
  `on_track | warning | urgent | breached`, derived from `elapsed_fraction` and the
  bands in `services/sla.py` rather than recomputed, so the screen and the emails
  cannot disagree.
- `GET /admin/contractors` — with `active_workload` and `rating`.
- `GET /admin/analytics` — counts by status, category and risk level; median
  resolution hours; SLA compliance.
- `GET /admin/analytics/performance` — per-contractor completed count, average
  resolution hours and rating.

**Every number is computed in SQL or in `services/`, never in the route**, and the
analytics tests use a fixture with known values so the assertions are arithmetic
rather than snapshots.

```python
def test_sla_state_uses_the_same_bands_as_the_emails(client): ...
def test_analytics_counts_only_the_officers_tenant(client, two_tenants): ...
def test_median_resolution_is_none_not_zero_with_nothing_resolved(client):
    """0 hours would read as instant resolution."""
```

- [ ] Expect **+12 tests**. Commit: `feat: work orders, contractors and analytics for the officer`.

---

### Task 5: The briefing and the email draft — closing Phase 2c's deferral

**Files:** modify `app/api/admin.py`; test `tests/api/test_admin_briefing.py`

- `GET /admin/briefing` — the most recent `DailyBriefing` for the tenant, **with
  `is_fallback` in the response**. v1 served template text for its entire life
  without anyone knowing; the flag must reach the screen, not just the table.
- `POST /admin/complaints/{id}/email-draft` — generate (calls `draft_department_email`,
  which *does* use a model: guard it so a quota failure returns 503 with a clear
  message rather than a 500).
- `POST /admin/complaints/{id}/email-draft/approve` — sets `email_approved`.
  Idempotent, and **refuses to approve an empty draft**.

This is the one task that touches a model, through the service built in Phase 2c. The
tests inject a fake chain exactly as the service's own tests do, so the suite still
makes no calls.

```python
def test_the_briefing_response_says_when_it_is_fallback_text(client): ...
def test_approving_an_empty_draft_is_refused(client): ...
def test_approving_twice_is_idempotent(client): ...
def test_a_model_outage_while_drafting_is_503_not_500(client): ...
```

- [ ] Expect **+9 tests**. Commit: `feat: expose the briefing and the email-draft approval to officers`.

---

### Task 6: The citizen OTP flow

**Files:** modify `app/api/complaints.py`, `app/db/models/` + migration; test `tests/api/test_citizen_otp.py`

`POST /complaints/verify-email` → sends a 6-digit code; `POST /complaints/verify-otp`
→ returns the complaints for that email. **Decide and record where the code lives**:
a `CitizenOtp` table keyed on email is preferable to columns on `User`, because a
citizen has no `User` row — v1 conflated the two.

The security properties are the point of this task:

```python
def test_the_code_is_not_in_the_verify_email_response(client):
    """It goes by email. Returning it would make the whole flow decorative."""


def test_requesting_a_code_for_an_unknown_email_looks_identical(client):
    """Otherwise the endpoint enumerates which citizens have complained."""


def test_a_code_expires(client): ...
def test_a_used_code_cannot_be_replayed(client): ...
def test_repeated_requests_are_rate_limited(client): ...
def test_a_wrong_code_does_not_reveal_whether_the_email_had_one(client): ...
def test_verify_otp_returns_only_that_email_s_complaints(client): ...
```

- [ ] Expect **+10 tests**. Commit: `feat: citizen email and OTP verification`.

---

### Task 7: The public dashboard

**Files:** create `app/api/public.py`, `app/schemas/public.py`; test `tests/api/test_public_dashboard.py`

`GET /public/dashboard?tenant_id=&state=&district=&category=` — counts, category
breakdown, recent resolved complaints, and the map points the Leaflet view needs.

**Unauthenticated, so it is the one place where leaking is easy.** No
`citizen_email`, no `citizen_phone`, no `citizen_name`, no `address`, no
`routing_justification`, and coordinates rounded to ~100 m. A test asserts the
response of a complaint with every field populated contains none of them — the same
discipline as `run_metadata` in `observability.py`.

```python
def test_the_dashboard_exposes_no_citizen_data(client): ...
def test_coordinates_are_coarsened(client): ...
def test_rejected_complaints_are_not_published(client):
    """A rejected complaint is a judgement about somebody's report."""
```

- [ ] Expect **+10 tests**. Commit: `feat: add the public dashboard`.

---

### Task 8: Wire the frontend to the real API

**Files:** modify `frontend/src/services/api.ts` and whichever screens the contract
breaks; no backend changes except bugs this finds

Run it. `npm install && npm run dev`, log in as `admin@civicai.gov`, click every
screen, and fix what breaks. Expect the response shapes to differ from v1's — that is
the point of doing it last, with the real contract in hand rather than guessed at.

- [ ] **Step 1: a screenshot of each working screen**, saved under
      `docs/screenshots/`, because Phase 6's README needs them and because a screen
      that has never been looked at is not finished.
- [ ] **Step 2:** record in this plan's carried-forward section every place the v1
      frontend assumed something the v2 API does not provide. That list is Phase 5's
      actual scope, measured rather than guessed.

---

## Phase 4a Done When

- [ ] `cd backend && .venv/bin/python -m pytest -q` passes — **~717 tests**, no network, no key
- [ ] `npm run dev` with the backend running: log in, see the complaint queue ordered by
      priority, open a complaint and read its citations, see the work orders with their
      SLA state, read the briefing, approve an email draft
- [ ] Every authenticated route has a no-token 401 test and a wrong-role 403 test
- [ ] Every list endpoint has a two-tenant isolation test and a capped page size
- [ ] `GET /public/dashboard` on a fully-populated complaint returns no email, phone,
      name, address or justification, and coarsened coordinates
- [ ] An unknown email and a wrong password are indistinguishable at `/admin/login`
- [ ] `docs/screenshots/` has one image per working screen

**Next:** Phase 4b — the officer ReAct agent, its tools and the SSE endpoint, built
onto this surface. It needs model quota, so it is the right thing to do on a day when
500 requests are available and the wrong thing to block a demo on.

---

## Carried forward from Phase 4a

What was deliberately deferred, and the known defects. **Read this before Phase 4b.**

### Endpoints the frontend wants that still do not exist

Three, all of them the citizen feedback loop rather than the officer surface:

| Endpoint | Why it was deferred |
|---|---|
| `POST /complaints/{id}/rate` | Satisfaction rating. `satisfaction_rating` and `satisfaction_comment` columns exist; nothing writes them. |
| `POST /complaints/{id}/verify` | "Was it actually fixed?" `verified_fixed` exists; nothing writes it. |
| `POST /admin/work-orders/{id}/completion-photo` | `completion_photo` exists. Needs the upload path *and* a decision about whether a completion photo is ever public — the public dashboard currently withholds all media. |

They are a coherent feature (closing the loop with the citizen), not three odds and
ends, and they belong with the frontend phase that will actually render them.

### Defects found by running it live, now fixed — and what that implies

All of these were invisible to a green suite:

- `AgentRun.started_at` was left to the column default, which fires at INSERT, so
  `finished_at` landed *before* `started_at` and any interval query read negative.
- The Gemini client's `max_retries` bypassed the shared rate limiter, making a 429
  storm self-amplifying. A `max_bucket_size` of 5 also broke the per-minute quota
  on the first burst alone.
- **A transient provider 503 permanently abandoned a complaint.** `UNFINISHED` listed
  only `"submitted"`, so the startup sweep looked for complaints that had never been
  started and ignored every complaint the graph had given up on.
- **And fixing that was not enough.** A failed node returns `{"errors": [...]}`
  rather than raising — deliberately, because retrieval is a soft dependency — so
  LangGraph checkpoints it as *complete*, and re-invoking the same thread replays the
  stored error without calling the model. The resume was a no-op that re-reported a
  stale failure in twenty milliseconds. A retry now runs on its own thread.

The last two are one story and it is the most instructive thing in this phase. A
gas-cylinder leak beside a bus stand was validated, classified `FIRE_HAZARD` at 0.99
confidence, and then lost — twice — to a provider that was briefly busy. It now
reaches risk critical, priority 94, a four-hour SLA and a contractor. **Nothing in the
test suite could have told us**, because both failures depended on a real provider
returning a real 503 at a real moment.

Note also that the eval harness had the *same* replay bug and the same fix: `load_log`
excludes errored rows so `--resume` cannot bake in an outage. That was fixed in Phase
3, and the identical trap in the graph went unrecognised for a phase and a half. The
shape of a bug recurs across layers that look nothing alike.

The lesson is already in CLAUDE.md and is worth restating: **every unit test passing
does not mean the system works.** Six of the six production bugs this project has
found were found by running it, not by testing it.

### Still unmeasured or unresolved

- **The validator is resolved, and the baseline it invalidated is not.** `validate`
  moved to v2 on 2026-10-06 after an A/B that was explicitly a trade
  (`docs/eval-reports/2026-10-06-validate-v1-vs-v2.md`): v1 wrongly rejected 9 real
  complaints in 40 and admitted no junk, v2 rejects 3 and admits 1. Promoted on the
  judgement that a terminal rejection with no appeal path costs a citizen far more
  than a junk row costs an officer. **Consequence: the core baseline's macro-F1 of
  0.93 was measured with v1 in front of `classify` and is now stale.** `core.json`
  records `validate_version` and says so. A re-baseline is a full sweep of ~555 calls
  and needs a day with the free-tier budget clear.
- **Risk grounding does not clearly pay for itself** (0.63 → 0.66, and that was
  measured on the wrong tier).
- **`multi_problem` classification is stuck at 0.67.**
- **1 in 6 prompt-injection items still moves its risk band.**
- **Faithfulness is unmeasured.** Citations are checked for *shape*, never for
  whether the cited chunk actually supports the sentence.
- **Judge labels:** 20 hand labels per criterion are still needed. The CLI and the
  artefact capture are built and waiting.

### Smaller things a reader will trip over

- **An officer cannot record *why* a status changed.** `PATCH /admin/complaints/{id}`
  takes a status and nothing else, because the table has no officer-note column.
  Adding one is a migration; it was written down rather than smuggled into an
  existing field.
- **`sla_state` is filtered in Python**, not SQL, since it depends on "now" against
  each order's own window. The page cap bounds the cost. A tenant with a hundred
  thousand orders needs the band precomputed on write.
- **The frontend's `PIPELINE_STAGES`/alias map references statuses v2 never writes**
  (`validated`, `classified`, `routed`, `grouped`). The tracking screen will render,
  but its progress bar is describing v1's lifecycle.
- **`/complaints/my` accepts and ignores an `email` query parameter.** Honouring it
  would undo the OTP flow entirely. The ignore is tested; the frontend should stop
  sending it.
