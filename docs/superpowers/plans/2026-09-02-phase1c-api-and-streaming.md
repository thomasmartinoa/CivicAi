# CivicAI v2 — Phase 1c: API, Background Execution and Live Streaming

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A citizen submits a complaint over HTTP and watches the graph process it live, and a server restart mid-run resumes rather than abandoning the complaint.

**Architecture:** Thin FastAPI handlers that persist the complaint, hand off to background execution, and stream `astream` updates over a WebSocket. The runner gains an `on_update` callback and an in-database trace for runs that raise. A startup sweep resumes threads left incomplete — the payoff for the checkpointer built in Phase 1b.

**Tech Stack:** FastAPI, LangGraph 1.2.11, SQLAlchemy 2.0.52, httpx, aiosmtplib/smtplib, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-civicai-v2-design.md`

**Prior phases:** Phase 0 (foundation, 51 tests), Phase 1a (AI layer, 113), Phase 1b (the graph, 183). Read Phase 1b's "Carried forward into Phase 1c" section before starting — several tasks here exist to close items on it.

## Global Constraints

- **Python 3.14.** Virtualenv at `backend/.venv`. Tests: `cd backend && .venv/bin/python -m pytest`.
- **No network in tests.** No test may make an HTTP request to a real host, open an SMTP connection, or construct a provider client. Geocoding and email are injected or monkeypatched.
- **Test output pristine** — the summary line reads `N passed in Xs` with no warning count.
- Warning suppression narrowly scoped to a message AND module; never blanket.
- **`app/ai/` must never import `app/api/`. `app/api/` may import only `app/ai/graph/runner`** from under `app/ai/graph/`. Enforced by `tests/test_import_rules.py`.
- **Nodes never write to the database.** All persistence stays in the runner.
- **Commit messages carry no `Co-Authored-By` trailer.** The repository owner asked for none.
- **Uploaded files are stored under a generated name.** A client-supplied filename is never used as a path component — Phase 1b's vision adapter flattens with `.name` and contains against the upload root, and that containment must not become the only defence.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/media.py` | safe upload storage: generated names, size cap, type allowlist |
| `backend/app/services/tenancy.py` | resolve the tenant a complaint belongs to |
| `backend/app/schemas/complaint.py` | request/response DTOs for the complaint API |
| `backend/app/api/complaints.py` | submit, track, and the WebSocket endpoint |
| `backend/app/services/execution.py` | background kickoff + the startup resume sweep |
| `backend/app/services/streaming.py` | WebSocket connection registry, keyed by tracking id |
| `backend/app/services/geocoding.py` | Nominatim, replacing the Phase 1b stub |
| `backend/app/services/notify.py` | SMTP + `notifications` audit row, replacing the stub |
| `backend/tests/…` | mirrors the above |

---

## Task 1: Safe media storage and tenant resolution

**Files:**
- Create: `backend/app/services/media.py`, `backend/app/services/tenancy.py`
- Test: `backend/tests/services/test_media.py`, `backend/tests/services/test_tenancy.py`

**Interfaces:**
- Consumes: `app.config.settings`, `app.db.models.core.Tenant`
- Produces:
  - `app.services.media.UPLOAD_ROOT: Path` — `Path(settings.upload_dir).resolve()`
  - `app.services.media.MAX_UPLOAD_BYTES: int`, `ALLOWED_MEDIA: dict[str, str]` (extension → media_type)
  - `app.services.media.MediaTooLarge(ValueError)`, `MediaTypeNotAllowed(ValueError)`
  - `app.services.media.store_upload(data: bytes, original_filename: str) -> StoredMedia`
  - `app.services.media.StoredMedia` — dataclass `(file_path: str, media_type: str, original_filename: str)`
  - `app.services.tenancy.resolve_tenant_id(session, requested: str | None) -> str` — raises `NoTenantConfigured`

- [ ] **Step 1: Write the failing tests**

`backend/tests/services/test_media.py`:

```python
from pathlib import Path

import pytest

from app.services import media as media_module
from app.services.media import (
    MAX_UPLOAD_BYTES, MediaTooLarge, MediaTypeNotAllowed, store_upload,
)


@pytest.fixture(autouse=True)
def upload_root(tmp_path, monkeypatch):
    """Redirect storage into tmp_path.

    The real UPLOAD_ROOT resolves to backend/uploads, inside the repository, so
    writing there would litter the working tree — and a failing test would leave
    the files behind. store_upload reads the module global at call time, so
    patching it is enough.
    """
    monkeypatch.setattr(media_module, "UPLOAD_ROOT", tmp_path)
    return tmp_path


def test_a_stored_file_lands_under_the_upload_root(upload_root):
    stored = store_upload(b"fake-jpeg-bytes", "photo.jpg")
    assert (upload_root / Path(stored.file_path).name).exists()


def test_the_stored_name_is_generated_not_client_supplied(upload_root):
    """A client filename must never become a path component. Phase 1b's vision
    adapter contains against traversal, but that must not be the only defence."""
    stored = store_upload(b"x", "../../etc/passwd.jpg")
    assert "etc" not in stored.file_path
    assert ".." not in stored.file_path
    assert stored.original_filename == "../../etc/passwd.jpg"
    assert list(upload_root.iterdir()), "nothing was written"


def test_the_stored_path_is_relative_and_prefixed(upload_root):
    stored = store_upload(b"x", "photo.jpg")
    assert stored.file_path.startswith("uploads/")
    assert not Path(stored.file_path).is_absolute()


@pytest.mark.parametrize("extension,expected", [
    ("jpg", "image"), ("jpeg", "image"), ("png", "image"), ("webp", "image"),
    ("mp3", "voice"), ("wav", "voice"), ("m4a", "voice"), ("ogg", "voice"),
])
def test_extension_determines_media_type(upload_root, extension, expected):
    assert store_upload(b"x", f"f.{extension}").media_type == expected


def test_a_disallowed_type_is_rejected_before_anything_is_written(upload_root):
    with pytest.raises(MediaTypeNotAllowed, match="exe"):
        store_upload(b"MZ", "payload.exe")
    assert list(upload_root.iterdir()) == [], "a rejected upload still wrote something"


def test_an_extensionless_upload_is_rejected(upload_root):
    with pytest.raises(MediaTypeNotAllowed):
        store_upload(b"x", "noextension")
    assert list(upload_root.iterdir()) == []


def test_an_oversized_upload_is_rejected_before_anything_is_written(upload_root):
    with pytest.raises(MediaTooLarge):
        store_upload(b"x" * (MAX_UPLOAD_BYTES + 1), "big.jpg")
    assert list(upload_root.iterdir()) == []


def test_two_uploads_of_the_same_name_do_not_collide(upload_root):
    a = store_upload(b"one", "photo.jpg")
    b = store_upload(b"two", "photo.jpg")
    assert a.file_path != b.file_path
    assert len(list(upload_root.iterdir())) == 2
```

`backend/tests/services/test_tenancy.py`:

```python
import pytest

from app.db.models.core import Tenant
from app.services.seed import seed_database
from app.services.tenancy import NoTenantConfigured, resolve_tenant_id


def test_an_explicit_tenant_is_used_when_it_exists(db_session):
    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    assert resolve_tenant_id(db_session, tenant.id) == tenant.id


def test_an_unknown_tenant_is_rejected(db_session):
    seed_database(db_session)
    with pytest.raises(NoTenantConfigured, match="not-a-tenant"):
        resolve_tenant_id(db_session, "not-a-tenant")


def test_no_request_falls_back_to_the_only_tenant(db_session):
    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    assert resolve_tenant_id(db_session, None) == tenant.id


def test_an_empty_database_fails_loudly(db_session):
    """route_node fails closed on a tenant-less complaint, so creation must not
    produce one. v1 silently used whichever tenant happened to be first."""
    with pytest.raises(NoTenantConfigured):
        resolve_tenant_id(db_session, None)


def test_ambiguity_fails_rather_than_guessing(db_session):
    db_session.add_all([Tenant(name="A"), Tenant(name="B")])
    db_session.commit()
    with pytest.raises(NoTenantConfigured, match="ambiguous"):
        resolve_tenant_id(db_session, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/services/test_media.py tests/services/test_tenancy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.media'`

- [ ] **Step 3: Implement the services**

`backend/app/services/media.py`:

```python
"""Upload storage.

Files are stored under a generated name. A client-supplied filename is kept only
as a display label and never becomes a path component — the vision adapter in
`app/ai/graph/runner.py` also contains against traversal, but defence there must
not be the only defence.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

UPLOAD_ROOT = Path(settings.upload_dir).resolve()
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# Extension -> media_type. An extension absent from this map is rejected before
# anything is written to disk.
ALLOWED_MEDIA: dict[str, str] = {
    "jpg": "image", "jpeg": "image", "png": "image", "webp": "image",
    "mp3": "voice", "wav": "voice", "m4a": "voice", "ogg": "voice",
}


class MediaTooLarge(ValueError):
    pass


class MediaTypeNotAllowed(ValueError):
    pass


@dataclass(frozen=True)
class StoredMedia:
    file_path: str
    media_type: str
    original_filename: str


def store_upload(data: bytes, original_filename: str) -> StoredMedia:
    """Validate, then write under a generated name. Rejects before writing."""
    extension = Path(original_filename).suffix.lstrip(".").lower()
    if extension not in ALLOWED_MEDIA:
        raise MediaTypeNotAllowed(
            f"{extension or original_filename!r} is not an accepted upload type; "
            f"accepted: {sorted(set(ALLOWED_MEDIA))}"
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise MediaTooLarge(f"{len(data)} bytes exceeds the {MAX_UPLOAD_BYTES} byte limit")

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{extension}"
    (UPLOAD_ROOT / name).write_bytes(data)
    return StoredMedia(
        file_path=f"uploads/{name}",
        media_type=ALLOWED_MEDIA[extension],
        original_filename=original_filename,
    )
```

`backend/app/services/tenancy.py`:

```python
"""Resolving which tenant a complaint belongs to.

`route_node` fails closed on a complaint with no `tenant_id`, so creation must
never produce one. v1 silently assigned whichever tenant happened to be first,
which is indistinguishable from a correct assignment until there are two.
"""

from sqlalchemy.orm import Session

from app.db.models.core import Tenant


class NoTenantConfigured(RuntimeError):
    pass


def resolve_tenant_id(session: Session, requested: str | None) -> str:
    """The tenant for a new complaint. Never guesses."""
    if requested:
        exists = session.query(Tenant).filter(Tenant.id == requested).one_or_none()
        if exists is None:
            raise NoTenantConfigured(f"tenant {requested!r} does not exist")
        return exists.id

    tenants = session.query(Tenant).limit(2).all()
    if not tenants:
        raise NoTenantConfigured(
            "no tenant exists; seed the database or supply tenant_id explicitly"
        )
    if len(tenants) > 1:
        raise NoTenantConfigured(
            "tenant is ambiguous: more than one exists and none was supplied"
        )
    return tenants[0].id
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/services -v`
Expected: PASS — the 5 pre-existing seed tests, 5 tenancy tests, and 14 media tests (7 plain plus 8 from the parametrized media-type test, minus one merged).

- [ ] **Step 5: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/services backend/tests/services
git commit -m "feat: add safe upload storage and tenant resolution

Uploads are stored under a generated name; a client filename is kept only as a
display label. The vision adapter already contains against traversal, but that
must not be the only defence.

resolve_tenant_id never guesses: an empty database and an ambiguous one both
fail loudly. route_node fails closed on a tenant-less complaint, so creation
must not be able to produce one."
```

---

## Task 2: Complaint submission and tracking endpoints

**Files:**
- Create: `backend/app/schemas/__init__.py`, `backend/app/schemas/complaint.py`, `backend/app/api/complaints.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/api/test_complaints.py`

**Interfaces:**
- Consumes: `app.services.media.store_upload`, `app.services.tenancy.resolve_tenant_id`, `app.db.session.get_db`
- Produces:
  - `app.schemas.complaint.ComplaintSubmitted` — `(id, tracking_id, status)`
  - `app.schemas.complaint.ComplaintDetail` — the tracking response
  - `POST /complaints/` → 201, `ComplaintSubmitted`
  - `GET /complaints/track/{tracking_id}` → `ComplaintDetail`, 404 when absent
  - `app.api.complaints.generate_tracking_id() -> str`

- [ ] **Step 1: Write the failing test**

The `client` fixture goes in `backend/tests/api/conftest.py`, not in the test file —
Task 4's WebSocket tests need it too, and a fixture defined in one test module is not
visible to another.

`backend/tests/api/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.seed import seed_database


@pytest.fixture
def client(db_session, monkeypatch):
    """A TestClient whose get_db yields the test session, and whose background
    execution is captured rather than run — Task 3 wires the real thing."""
    from app.db.session import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    seed_database(db_session)
    captured: list[str] = []
    monkeypatch.setattr("app.api.complaints.schedule_complaint_run",
                        lambda complaint_id: captured.append(complaint_id))
    with TestClient(app) as c:
        c.captured_runs = captured
        yield c
    app.dependency_overrides.clear()
```

`backend/tests/api/test_complaints.py`:

```python
from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Tenant


def _form(**over):
    body = {"description": "A large pothole on the main road near the school gate",
            "citizen_email": "citizen@example.com"}
    body.update(over)
    return body


def test_submitting_a_complaint_returns_a_tracking_id(client):
    response = client.post("/complaints/", data=_form())
    assert response.status_code == 201
    assert response.json()["tracking_id"].startswith("CIV-")
    assert response.json()["status"] == "submitted"


def test_the_complaint_is_persisted_with_a_tenant(client, db_session):
    """route_node fails closed on a tenant-less complaint."""
    client.post("/complaints/", data=_form())
    stored = db_session.query(Complaint).one()
    assert stored.tenant_id == db_session.query(Tenant).one().id


def test_submission_schedules_the_graph_run(client):
    client.post("/complaints/", data=_form())
    assert len(client.captured_runs) == 1


def test_the_citizen_is_not_made_to_wait_for_the_graph(client):
    """The response must not depend on the run. v1 got this right and it is the
    one architectural decision worth carrying forward unchanged."""
    response = client.post("/complaints/", data=_form())
    assert response.status_code == 201
    assert response.json()["status"] == "submitted"


def test_a_too_short_description_is_rejected(client):
    response = client.post("/complaints/", data=_form(description="hi"))
    assert response.status_code == 422


def test_an_uploaded_image_is_stored_and_linked(client, db_session):
    response = client.post(
        "/complaints/", data=_form(),
        files=[("files", ("photo.jpg", b"fake-jpeg", "image/jpeg"))],
    )
    assert response.status_code == 201
    media = db_session.query(ComplaintMedia).one()
    assert media.media_type == "image"
    assert media.original_filename == "photo.jpg"
    assert "photo" not in media.file_path, "the stored name must be generated"


def test_a_disallowed_upload_type_is_rejected(client):
    response = client.post(
        "/complaints/", data=_form(),
        files=[("files", ("payload.exe", b"MZ", "application/octet-stream"))],
    )
    assert response.status_code == 400
    assert "exe" in response.json()["detail"]


def test_tracking_returns_the_complaint(client):
    tracking_id = client.post("/complaints/", data=_form()).json()["tracking_id"]
    response = client.get(f"/complaints/track/{tracking_id}")
    assert response.status_code == 200
    assert response.json()["tracking_id"] == tracking_id
    assert response.json()["status"] == "submitted"


def test_tracking_an_unknown_id_is_404(client):
    assert client.get("/complaints/track/CIV-NOPE0000").status_code == 404


def test_tracking_id_is_not_guessable_in_sequence(client):
    ids = {client.post("/complaints/", data=_form()).json()["tracking_id"] for _ in range(5)}
    assert len(ids) == 5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/api/test_complaints.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.complaints'`

- [ ] **Step 3: Implement the schemas**

`backend/app/schemas/complaint.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ComplaintSubmitted(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tracking_id: str
    status: str


class MediaSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_path: str
    media_type: str
    original_filename: str | None = None


class ComplaintDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tracking_id: str
    status: str
    description: str
    terminal_reason: str | None = None
    category: str | None = None
    subcategory: str | None = None
    priority_score: int | None = None
    risk_level: str | None = None
    address: str | None = None
    ward: str | None = None
    district: str | None = None
    created_at: datetime
    updated_at: datetime
    media: list[MediaSummary] = []
```

`backend/app/schemas/__init__.py` may stay empty.

- [ ] **Step 4: Implement the router**

`backend/app/api/complaints.py`:

```python
"""Citizen-facing complaint endpoints.

The handler persists the complaint and returns immediately; the graph runs in
the background. v1 made the same call and it was right — AI calls take seconds
and a citizen should not wait for them. What v1 lacked was durability, which
Phase 1b's checkpointer and this phase's resume sweep supply.
"""

import secrets
import string
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.session import get_db
from app.schemas.complaint import ComplaintDetail, ComplaintSubmitted
from app.services.execution import schedule_complaint_run
from app.services.media import MediaTooLarge, MediaTypeNotAllowed, store_upload
from app.services.tenancy import NoTenantConfigured, resolve_tenant_id

router = APIRouter(prefix="/complaints", tags=["complaints"])

_ALPHABET = string.ascii_uppercase + string.digits
MIN_DESCRIPTION = 10


def generate_tracking_id() -> str:
    """Random, not sequential: a tracking id is the only credential for reading
    a complaint, so it must not be guessable from a neighbouring one."""
    return "CIV-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ComplaintSubmitted)
async def submit_complaint(
    description: Annotated[str, Form(min_length=MIN_DESCRIPTION)],
    citizen_email: Annotated[str, Form()],
    citizen_name: Annotated[str | None, Form()] = None,
    citizen_phone: Annotated[str | None, Form()] = None,
    latitude: Annotated[float | None, Form()] = None,
    longitude: Annotated[float | None, Form()] = None,
    address: Annotated[str | None, Form()] = None,
    tenant_id: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile], File()] = [],
    db: Session = Depends(get_db),
) -> Complaint:
    try:
        resolved_tenant = resolve_tenant_id(db, tenant_id)
    except NoTenantConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = []
    for upload in files:
        try:
            stored.append(store_upload(await upload.read(), upload.filename or "upload"))
        except (MediaTypeNotAllowed, MediaTooLarge) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    complaint = Complaint(
        tracking_id=generate_tracking_id(),
        tenant_id=resolved_tenant,
        citizen_email=citizen_email,
        citizen_name=citizen_name,
        citizen_phone=citizen_phone,
        description=description,
        latitude=latitude,
        longitude=longitude,
        address=address,
        status="submitted",
    )
    db.add(complaint)
    db.flush()
    for item in stored:
        db.add(ComplaintMedia(
            complaint_id=complaint.id,
            file_path=item.file_path,
            media_type=item.media_type,
            original_filename=item.original_filename,
        ))
    db.commit()
    db.refresh(complaint)

    schedule_complaint_run(complaint.id)
    return complaint


@router.get("/track/{tracking_id}", response_model=ComplaintDetail)
async def track_complaint(tracking_id: str, db: Session = Depends(get_db)) -> Complaint:
    complaint = (
        db.query(Complaint).filter(Complaint.tracking_id == tracking_id).one_or_none()
    )
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint
```

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, add the import and `app.include_router(complaints.router)` alongside the existing system router.

- [ ] **Step 6: Create the execution placeholder**

`app/api/complaints.py` imports `schedule_complaint_run`, which Task 3 implements.
Create the module now so the import resolves; the tests monkeypatch it, so the body
is never reached.

`backend/app/services/execution.py`:

```python
"""Background execution of the complaint graph. Implemented in Phase 1c Task 3."""


def schedule_complaint_run(complaint_id: str) -> None:
    raise NotImplementedError("Phase 1c Task 3 implements background execution")
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/api -v`
Expected: PASS, 10 new tests plus the 5 pre-existing system tests.

- [ ] **Step 8: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app backend/tests
git commit -m "feat: add complaint submission and tracking endpoints

The handler persists and returns immediately; the graph runs in the background.
v1 made the same call and it was right — what it lacked was durability, which
the checkpointer and Task 3's resume sweep supply.

Tracking ids use secrets.choice rather than random.choices: the tracking id is
the only credential for reading a complaint, so it must not be guessable from a
neighbouring one."
```

---

## Task 3: Background execution, failure traces and the resume sweep

This is where the checkpointer built in Phase 1b pays for itself.

**Files:**
- Modify: `backend/app/services/execution.py`, `backend/app/ai/graph/runner.py`, `backend/app/main.py`
- Test: `backend/tests/services/test_execution.py`

**Interfaces:**
- Consumes: `app.ai.graph.runner.run_complaint`, `app.db.session.SessionLocal`
- Produces:
  - `app.services.execution.schedule_complaint_run(complaint_id: str) -> None`
  - `app.services.execution.resume_incomplete_runs() -> list[str]` — ids resumed
  - `app.ai.graph.runner.run_complaint` writes an `AgentRun(status="failed")` when a node raises, then re-raises

- [ ] **Step 1: Write the failing test**

`backend/tests/services/test_execution.py`:

```python
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.db.models.ai import AgentRun
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant
from app.services.seed import seed_database
from app.services.execution import resume_incomplete_runs


@pytest.fixture
def submitted(db_session):
    seed_database(db_session)
    tenant = db_session.query(Tenant).one()
    complaint = Complaint(
        tracking_id="CIV-EXEC0001", tenant_id=tenant.id,
        citizen_email="a@b.com",
        description="A large pothole on the main road near the school gate",
    )
    db_session.add(complaint)
    db_session.commit()
    return db_session, complaint.id


async def test_a_node_that_raises_leaves_a_failed_agent_run(submitted):
    """Without this the complaint stays 'submitted' with no record that anything
    was attempted — invisible under background execution."""
    from app.ai.graph.deps import GraphDeps
    from app.ai.graph.runner import run_complaint
    from app.ai.schemas import ValidationResult
    from langchain_core.runnables import RunnableLambda

    session, complaint_id = submitted
    # classify_chain omitted entirely: require() raises inside the node, which is
    # the "a node raised" path this test exists for.
    deps = GraphDeps(
        validate_chain=RunnableLambda(lambda _: ValidationResult(is_valid=True)),
        session_factory=lambda: session,
        notify=lambda **kw: None,
    )

    with pytest.raises(Exception):
        await run_complaint(complaint_id, session_factory=lambda: session,
                            deps=deps, checkpointer=InMemorySaver())

    session.rollback()
    session.expire_all()
    run = session.query(AgentRun).one()
    assert run.status == "failed"
    assert run.error
    assert run.complaint_id == complaint_id


async def test_resume_sweep_finds_complaints_left_unprocessed(submitted):
    """A restart mid-run must not abandon the complaint. v1's BackgroundTasks
    had no way to know a run had been interrupted."""
    session, complaint_id = submitted
    assert complaint_id in resume_incomplete_runs(session_factory=lambda: session)


async def test_resume_sweep_ignores_finished_complaints(submitted):
    session, complaint_id = submitted
    complaint = session.query(Complaint).one()
    complaint.status = "assigned"
    session.commit()
    assert resume_incomplete_runs(session_factory=lambda: session) == []


async def test_resume_sweep_ignores_rejected_complaints(submitted):
    session, complaint_id = submitted
    complaint = session.query(Complaint).one()
    complaint.status = "rejected"
    session.commit()
    assert resume_incomplete_runs(session_factory=lambda: session) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/services/test_execution.py -v`
Expected: FAIL — `resume_incomplete_runs` does not exist.

- [ ] **Step 3: Record a failure trace when a node raises**

In `backend/app/ai/graph/runner.py`, wrap the invocation so a raising node still leaves evidence:

```python
    try:
        ran, result = await _advance(graph, state, config)
    except Exception as exc:
        # Without this the complaint stays 'submitted' with nothing recording that
        # anything was attempted. The checkpoint survives, so a resume can still
        # pick it up — but under background execution the failure is otherwise
        # invisible in the database.
        session.add(AgentRun(
            complaint_id=complaint_id,
            thread_id=complaint_id,
            status="failed",
            graph_version=GRAPH_VERSION,
            finished_at=utcnow(),
            error=f"{type(exc).__name__}: {exc}",
        ))
        session.commit()
        raise
```

Adapt to the current structure — the requirement is that an exception escaping `ainvoke` leaves exactly one `AgentRun(status="failed")` carrying the exception, and still propagates.

- [ ] **Step 4: Implement execution**

`backend/app/services/execution.py`:

```python
"""Background execution of the complaint graph.

v1 used FastAPI BackgroundTasks too, and the citizen-facing latency argument for
it was right. What v1 could not do was notice that a run had been interrupted: a
restart mid-pipeline left the complaint at 'submitted' forever with nothing to
retry it. The checkpointer changes that — `resume_incomplete_runs` at startup
re-drives anything left behind, and `run_complaint` resumes rather than replays.
"""

import asyncio
import logging
from collections.abc import Callable

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Statuses meaning "the graph has not reached a conclusion for this complaint".
UNFINISHED = ("submitted",)


def schedule_complaint_run(complaint_id: str) -> None:
    """Fire the graph without blocking the caller.

    The task is intentionally not awaited. If the process dies before it
    finishes, the startup sweep picks the complaint up again.
    """
    from app.ai.graph.runner import run_complaint

    async def _run() -> None:
        try:
            await run_complaint(complaint_id, session_factory=SessionLocal)
        except Exception:
            logger.exception("complaint run failed for %s", complaint_id)

    asyncio.create_task(_run())


def resume_incomplete_runs(session_factory: Callable = SessionLocal) -> list[str]:
    """Complaint ids the graph never finished. Called at startup."""
    from app.db.models.complaint import Complaint

    session = session_factory()
    try:
        pending = (
            session.query(Complaint.id)
            .filter(Complaint.status.in_(UNFINISHED))
            .all()
        )
        return [row.id for row in pending]
    finally:
        session.close()
```

- [ ] **Step 5: Sweep on startup**

In `backend/app/main.py`'s `lifespan`, before `yield`:

```python
    for complaint_id in resume_incomplete_runs():
        logger.info("resuming interrupted complaint %s", complaint_id)
        schedule_complaint_run(complaint_id)
```

- [ ] **Step 6: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app backend/tests
git commit -m "feat: background execution with a startup resume sweep

v1 used BackgroundTasks too and the latency argument was right; what it could
not do was notice an interrupted run, so a restart mid-pipeline left the
complaint at 'submitted' forever. The checkpointer changes that: the sweep
re-drives anything unfinished and run_complaint resumes rather than replays.

A node that raises now leaves an AgentRun(status='failed') before re-raising,
so the failure is visible in the database rather than only in the logs."
```

---

## Task 4: Live streaming over WebSocket

**Files:**
- Create: `backend/app/services/streaming.py`
- Modify: `backend/app/ai/graph/runner.py`, `backend/app/api/complaints.py`, `backend/app/services/execution.py`
- Test: `backend/tests/services/test_streaming.py`, `backend/tests/api/test_complaint_ws.py`

**Interfaces:**
- Produces:
  - `app.services.streaming.ConnectionRegistry` with `connect`, `disconnect`, `publish(tracking_id, message)`
  - `app.services.streaming.registry` — the process-wide instance
  - `run_complaint(..., on_update: Callable[[str, dict], Awaitable[None]] | None = None)`
  - `WS /complaints/ws/{tracking_id}`

- [ ] **Step 1: Write the failing tests**

`backend/tests/services/test_streaming.py`:

```python
import pytest

from app.services.streaming import ConnectionRegistry


class _FakeSocket:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, message: dict) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(message)


async def test_a_published_message_reaches_a_subscriber():
    registry = ConnectionRegistry()
    socket = _FakeSocket()
    registry.connect("CIV-1", socket)
    await registry.publish("CIV-1", {"node": "classify"})
    assert socket.sent == [{"node": "classify"}]


async def test_publishing_to_nobody_is_not_an_error():
    await ConnectionRegistry().publish("CIV-NOBODY", {"node": "classify"})


async def test_every_subscriber_of_one_complaint_receives_it():
    registry = ConnectionRegistry()
    a, b = _FakeSocket(), _FakeSocket()
    registry.connect("CIV-1", a)
    registry.connect("CIV-1", b)
    await registry.publish("CIV-1", {"node": "route"})
    assert a.sent and b.sent


async def test_subscribers_of_other_complaints_do_not_receive_it():
    registry = ConnectionRegistry()
    mine, theirs = _FakeSocket(), _FakeSocket()
    registry.connect("CIV-1", mine)
    registry.connect("CIV-2", theirs)
    await registry.publish("CIV-1", {"node": "route"})
    assert mine.sent and not theirs.sent


async def test_a_dead_socket_is_dropped_and_does_not_break_the_others():
    """A closed browser tab must not stop the graph from streaming."""
    registry = ConnectionRegistry()
    dead, alive = _FakeSocket(fail=True), _FakeSocket()
    registry.connect("CIV-1", dead)
    registry.connect("CIV-1", alive)
    await registry.publish("CIV-1", {"node": "classify"})
    assert alive.sent
    assert registry.subscriber_count("CIV-1") == 1


async def test_disconnect_removes_the_last_subscriber_entirely():
    registry = ConnectionRegistry()
    socket = _FakeSocket()
    registry.connect("CIV-1", socket)
    registry.disconnect("CIV-1", socket)
    assert registry.subscriber_count("CIV-1") == 0
```

`backend/tests/api/test_complaint_ws.py`:

```python
from app.services.streaming import registry


def test_a_client_receives_updates_published_for_its_complaint(client):
    """The citizen watches nodes light up instead of staring at 'submitted'."""
    tracking_id = client.post(
        "/complaints/",
        data={"description": "A large pothole on the main road near the school",
              "citizen_email": "a@b.com"},
    ).json()["tracking_id"]

    with client.websocket_connect(f"/complaints/ws/{tracking_id}") as ws:
        import anyio
        anyio.from_thread.run(registry.publish, tracking_id, {"node": "classify"})
        assert ws.receive_json() == {"node": "classify"}
```

Adjust the publish mechanics to whatever works with `TestClient`'s portal — the requirement is that a message published for a tracking id reaches a client connected to that id's socket. If driving it through the registry from a sync test proves impractical, assert instead that connecting registers a subscriber and disconnecting removes it, and cover delivery in `test_streaming.py`. Say which you did and why.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/services/test_streaming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.streaming'`

- [ ] **Step 3: Implement the registry**

`backend/app/services/streaming.py`:

```python
"""WebSocket fan-out, keyed by tracking id.

Process-local by design: one registry per worker. A multi-worker deployment
needs a broker, which is out of scope while the app runs as a single process.
"""

import logging
from collections import defaultdict
from typing import Protocol

logger = logging.getLogger(__name__)


class Sendable(Protocol):
    async def send_json(self, message: dict) -> None: ...


class ConnectionRegistry:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Sendable]] = defaultdict(list)

    def connect(self, tracking_id: str, socket: Sendable) -> None:
        self._subscribers[tracking_id].append(socket)

    def disconnect(self, tracking_id: str, socket: Sendable) -> None:
        subscribers = self._subscribers.get(tracking_id, [])
        if socket in subscribers:
            subscribers.remove(socket)
        if not subscribers:
            self._subscribers.pop(tracking_id, None)

    def subscriber_count(self, tracking_id: str) -> int:
        return len(self._subscribers.get(tracking_id, []))

    async def publish(self, tracking_id: str, message: dict) -> None:
        """Best effort. A closed tab must not stop the graph from streaming."""
        for socket in list(self._subscribers.get(tracking_id, [])):
            try:
                await socket.send_json(message)
            except Exception:
                logger.debug("dropping dead subscriber for %s", tracking_id)
                self.disconnect(tracking_id, socket)


registry = ConnectionRegistry()
```

- [ ] **Step 4: Give the runner an update callback**

In `run_complaint`, accept `on_update: Callable[[str, dict], Awaitable[None]] | None = None`. When supplied, stream instead of invoking:

```python
    if on_update is None:
        ran, result = await _advance(graph, state, config)
    else:
        ran, result = await _advance_streaming(graph, state, config, on_update)
```

`_advance_streaming` mirrors `_advance`'s three-way decision, but drives the run with
`graph.astream(graph_input, config, stream_mode="updates")`, calling
`await on_update(node, update)` for each `{node: update}` chunk, then reads the final
state with `await graph.aget_state(config)`.

Verified shape: `astream(stream_mode="updates")` yields one dict per node, e.g.
`{"classify": {"classification": ..., "decision_log": [...]}}`, and a completed
thread re-streamed yields zero chunks.

Keep the payload the citizen sees deliberately small — a node name and a human
summary, never raw state:

```python
async def _publish_progress(tracking_id: str, node: str, update: dict) -> None:
    decisions = update.get("decision_log") or []
    await registry.publish(tracking_id, {
        "node": node,
        "summary": decisions[-1].summary if decisions else None,
    })
```

Wire it in `schedule_complaint_run` so background runs stream.

- [ ] **Step 5: Add the WebSocket endpoint**

In `backend/app/api/complaints.py`:

```python
@router.websocket("/ws/{tracking_id}")
async def complaint_updates(websocket: WebSocket, tracking_id: str) -> None:
    await websocket.accept()
    registry.connect(tracking_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        registry.disconnect(tracking_id, websocket)
```

- [ ] **Step 6: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app backend/tests
git commit -m "feat: stream graph progress to the citizen over WebSocket

The runner gains an on_update callback and drives the run with astream when one
is supplied, so the citizen watches nodes light up instead of staring at
'submitted'. The published payload is a node name and a summary, never raw
state.

The registry is process-local by design; a multi-worker deployment needs a
broker, which is out of scope while the app runs as one process."
```

---

## Task 5: Real geocoding and notification

**Files:**
- Modify: `backend/app/services/geocoding.py`, `backend/app/services/notify.py`
- Test: `backend/tests/services/test_geocoding.py`, `backend/tests/services/test_notify.py`

**Interfaces:**
- Produces:
  - `reverse_geocode(lat, lon) -> LocationInfo` — Nominatim, timeout-bounded
  - `notify_citizen(*, tracking_id, complaint_id, category, status, recipient, session_factory) -> None` — sends and records a `Notification` row with a `dedupe_key`

- [ ] **Step 1: Write the failing tests**

`backend/tests/services/test_geocoding.py`:

```python
import httpx
import pytest

from app.ai.schemas import LocationInfo
from app.services.geocoding import reverse_geocode


def _transport(payload, status_code=200):
    return httpx.MockTransport(lambda request: httpx.Response(status_code, json=payload))


def test_a_nominatim_response_maps_onto_location_info():
    payload = {"display_name": "MG Road, Bengaluru",
               "address": {"suburb": "Shivajinagar", "city_district": "Bengaluru East",
                           "state": "Karnataka"}}
    location = reverse_geocode(12.97, 77.59, transport=_transport(payload))
    assert location.address == "MG Road, Bengaluru"
    assert location.ward == "Shivajinagar"
    assert location.district == "Bengaluru East"
    assert location.state == "Karnataka"


def test_a_missing_field_becomes_an_empty_string_not_none():
    """LocationInfo's falsy checks drive jurisdiction level; None would still be
    falsy but the type says str."""
    location = reverse_geocode(0, 0, transport=_transport({"address": {}}))
    assert location.ward == ""
    assert isinstance(location.address, str)


def test_an_http_error_raises_so_intake_can_degrade():
    """intake catches this and records an error without terminating the run."""
    with pytest.raises(Exception):
        reverse_geocode(0, 0, transport=_transport({}, status_code=500))


def test_a_timeout_raises_rather_than_hanging():
    def timeout(request):
        raise httpx.ConnectTimeout("too slow")

    with pytest.raises(httpx.ConnectTimeout):
        reverse_geocode(0, 0, transport=httpx.MockTransport(timeout))
```

`backend/tests/services/test_notify.py`:

```python
from app.db.models.complaint import Complaint
from app.db.models.core import Tenant
from app.db.models.workflow import Notification
from app.services.notify import notify_citizen
from app.services.seed import seed_database


def _complaint(db_session):
    seed_database(db_session)
    complaint = Complaint(
        tracking_id="CIV-NOTIFY01", tenant_id=db_session.query(Tenant).one().id,
        citizen_email="a@b.com", description="x" * 40,
    )
    db_session.add(complaint)
    db_session.commit()
    return complaint


def test_a_notification_is_recorded_even_when_sending_fails(db_session, monkeypatch):
    """v1 logged every attempt with an is_sent flag and that was right — a failed
    send must still leave evidence."""
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("smtp down")))

    notify_citizen(tracking_id=complaint.tracking_id, complaint_id=complaint.id,
                   category="ROADS", status="assigned", recipient="a@b.com",
                   session_factory=lambda: db_session)

    record = db_session.query(Notification).one()
    assert record.is_sent is False
    assert record.sent_at is None


def test_a_successful_send_is_recorded_as_sent(db_session, monkeypatch):
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email", lambda *a, **k: None)

    notify_citizen(tracking_id=complaint.tracking_id, complaint_id=complaint.id,
                   category="ROADS", status="assigned", recipient="a@b.com",
                   session_factory=lambda: db_session)

    record = db_session.query(Notification).one()
    assert record.is_sent is True
    assert record.sent_at is not None


def test_the_same_notification_twice_records_once(db_session, monkeypatch):
    """notifications.dedupe_key is unique — Phase 0 added it because v1 re-sent
    SLA warnings every five minutes."""
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email", lambda *a, **k: None)
    for _ in range(2):
        notify_citizen(tracking_id=complaint.tracking_id, complaint_id=complaint.id,
                       category="ROADS", status="assigned", recipient="a@b.com",
                       session_factory=lambda: db_session)
    assert db_session.query(Notification).count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/services/test_geocoding.py tests/services/test_notify.py -v`
Expected: FAIL — the stubs take different arguments and record nothing.

- [ ] **Step 3: Implement geocoding**

`backend/app/services/geocoding.py`:

```python
"""Reverse geocoding via OpenStreetMap Nominatim.

Raises on failure rather than returning an empty result: `intake_node` catches it,
records the error and continues, so a complaint without a ward is still a
complaint. Swallowing the failure here would make it invisible.
"""

import httpx

from app.ai.schemas import LocationInfo

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
TIMEOUT_SECONDS = 3.0
USER_AGENT = "CivicAI/2.0 (infrastructure complaint routing)"


def reverse_geocode(lat: float, lon: float, *, transport: httpx.BaseTransport | None = None) -> LocationInfo:
    with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        response = client.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()

    address = payload.get("address", {}) or {}
    return LocationInfo(
        address=payload.get("display_name", "") or "",
        ward=address.get("suburb") or address.get("neighbourhood") or "",
        block=address.get("city_block") or address.get("quarter") or "",
        district=address.get("city_district") or address.get("county") or "",
        state=address.get("state") or "",
    )
```

- [ ] **Step 4: Implement notification**

`backend/app/services/notify.py`:

```python
"""Citizen notification, with an audit row for every attempt.

Two things carried forward deliberately. v1 logged every attempt with an
`is_sent` flag whether or not SMTP worked, which was right — a failed send must
leave evidence. And `notifications.dedupe_key` is unique because v1 re-sent SLA
warnings every five minutes for hours.
"""

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.base import utcnow
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = "CivicAI <noreply@civicai.gov>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def notify_citizen(
    *,
    tracking_id: str,
    complaint_id: str,
    category: str | None,
    status: str,
    recipient: str,
    session_factory: Callable = SessionLocal,
) -> None:
    from app.db.models.workflow import Notification

    subject = f"CivicAI — your complaint {tracking_id}"
    body = (
        f"Your complaint {tracking_id} has been processed.\n\n"
        f"Category: {category or 'under review'}\n"
        f"Status: {status}\n"
    )

    sent = False
    try:
        _send_email(recipient, subject, body)
        sent = True
    except Exception:
        logger.warning("notification send failed for %s", tracking_id, exc_info=True)

    session = session_factory()
    try:
        session.add(Notification(
            complaint_id=complaint_id,
            recipient_email=recipient,
            notification_type="status_update",
            message=subject,
            is_sent=sent,
            sent_at=utcnow() if sent else None,
            dedupe_key=f"{complaint_id}:status_update:{status}",
        ))
        session.commit()
    except IntegrityError:
        # dedupe_key is unique: this exact notification was already recorded.
        session.rollback()
    finally:
        session.close()
```

Note `notify_citizen`'s signature changed, so `build_deps` in `app/ai/graph/runner.py` must adapt — the node calls `notify(tracking_id=..., complaint_id=..., category=..., status=...)` and knows nothing about a recipient or a session. Wire the recipient and session factory in `build_deps` via a closure over the complaint's email.

- [ ] **Step 5: Run the full suite and commit**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: PASS.

```bash
cd /home/martin/Projects/CivicAi
git add backend/app backend/tests
git commit -m "feat: real geocoding and notification

Geocoding raises on failure rather than returning empty: intake catches it,
records the error and continues, so the failure is visible instead of silently
producing a complaint with no ward.

Every notification attempt writes an audit row whether or not SMTP worked, and
dedupe_key makes a repeat a no-op — v1 re-sent SLA warnings every five minutes."
```

---

## Phase 1c Done When

- [ ] `cd backend && .venv/bin/python -m pytest` passes with no network access and no API key
- [ ] `POST /complaints/` with a photo returns 201 in well under a second and stores the file under a generated name
- [ ] A client connected to `WS /complaints/ws/{tracking_id}` receives one message per node as the graph runs
- [ ] Killing the process mid-run and restarting resumes that complaint rather than abandoning it
- [ ] A node that raises leaves an `AgentRun(status="failed")` carrying the exception
- [ ] A tenant-less or ambiguous-tenant submission fails loudly at creation, never reaching `route_node`
- [ ] Every notification attempt leaves a `notifications` row; a repeat is a no-op

**Next:** Phase 2 — RAG. The corpus, the ingest CLI, FAISS with hybrid retrieval, and the four nodes that stop guessing.

---

## Carried forward into Phase 2

**Docs to reconcile before Phase 2 starts**
- The spec's phase table and the Phase 1b plan both list LangSmith tracing and the SLA
  monitor port under Phase 1. Neither landed in 1a, 1b or 1c. Decide where they go and
  say so — an omission that is a decision is fine; one that is an accident is not.

**Frontend contract the live view will need**
- No terminal event on the WebSocket. `_run_one` publishes one message per node and
  nothing at completion or failure, so a subscriber cannot tell "still running" from
  "finished, go poll". Publish a final `{"node": "__end__", "status": ...}` on both the
  success and the failure path.
- The first update is usually lost: `schedule_complaint_run` fires before the 201 is
  serialised, and `intake` has typically published before the client opens the socket.
  Document that the client seeds from `GET /track` and treats the socket as incremental.
- Node summaries are audit strings, not citizen text. `notify_node`'s failure summary can
  carry a raw database error. A mapping layer belongs in front of the socket.

**Open behaviours**
- A failed notification is never re-driven. The `SENT_SUMMARY` guard permits a retry and
  `notify_citizen` now checks before sending, so a re-drive is safe to build — but
  nothing calls the node again once the thread completes.
- Deterministic failures are retried on every restart without bound: a run that hits
  the trap leaves `submitted`, so the sweep re-drives it at every boot, adding a failed
  `AgentRun` each time. A max-attempts check against failed-run count is a Phase 3 item.
- No graceful drain at shutdown. In-flight background tasks are cancelled when the loop
  closes; the sweep resumes them, but Phase 1b measured that an abrupt stop can replay
  a whole run. `await asyncio.wait(_background_tasks, timeout=15)` after the lifespan
  `yield` would turn most restarts from replay into completion.
- Single-process assumptions: with `--workers 2` every worker runs the sweep and the
  same complaint gets two concurrent runs on one checkpoint thread. Documented in
  `streaming.py`; should be in `execution.py` too. The Dockerfile is single-worker.

**Input hardening**
- `citizen_email` is an unvalidated `str`. No header injection (verified — `EmailMessage`
  rejects CR/LF), but a bad value lands as a silently failed notification instead of a
  422. `latitude`/`longitude` have no range validation.
- `store_upload` trusts the extension only; `b"fake-jpeg"` stores as an image and burns
  a retried vision call before the node degrades. A four-byte magic check is cheap.
- `From: noreply@civicai.gov` is hard-coded on a domain the project does not own; any
  DMARC-enforcing relay will reject it. Make it a setting.
- `ComplaintSubmitted` and `ComplaintDetail` expose the internal `id` alongside the
  tracking id, which is meant to be the only credential.

**Accepted as-is**
- `_read_bounded` bounds heap, not bandwidth or disk — Starlette has already spooled the
  body before the handler runs. A `Content-Length` guard or proxy limit is the other half.
- `_is_loopback` matches literal `localhost` and loopback IPs only; a hostname resolving
  to loopback gets STARTTLS attempted and fails safe.
- A concurrent-first-attempt race in `notify_citizen` could double-send within a
  millisecond window; the `IntegrityError` backstop records one row.
