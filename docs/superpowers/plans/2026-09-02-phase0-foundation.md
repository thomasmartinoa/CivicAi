# CivicAI v2 — Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 backend with a clean, tested foundation — configuration, database layer, migrations and seed data — that boots and is ready for the LangGraph pipeline in Phase 1.

**Architecture:** Greenfield in-place rewrite of `backend/app/`. v1's AI code is deleted (it is documented in `docs/01-legacy-system-explained.md` and preserved in git history); only its keyword classifier survives, ported into `app/evals/baseline.py` as the eval harness's naive baseline. The new tree separates `db/`, `api/`, `services/`, `ai/` and `evals/`, with a strict rule that `ai/` never imports `api/`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (typed `Mapped[]`), SQLite, Alembic, pydantic-settings, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-civicai-v2-design.md`

**Prior art:** `docs/01-legacy-system-explained.md` — read section 7 (data model) and section 10 (bugs) before starting. Task 5 exists specifically to prevent v1's Bug 3 from recurring.

## Global Constraints

- **Python 3.14.** All dependencies must have cp314-compatible wheels.
- **Package versions** (pin exactly): `fastapi==0.115.0`, `sqlalchemy==2.0.52`, `alembic==1.13.2`, `pydantic==2.12.3`, `pydantic-settings==2.5.0`, `pytest==8.3.3`, `pytest-asyncio==0.24.0`.
  - `sqlalchemy` is 2.0.52, **not** 2.0.35: under Python 3.14, SQLAlchemy 2.0.35 raises
    `TypeError: descriptor '__getitem__' requires a 'typing.Union' object but received a 'tuple'`
    at class-definition time for any `Mapped[X | None]` column annotation. 2.0.52 handles it and
    correctly infers `nullable=True` from the union, so the idiomatic annotation stays.
  - `pydantic` is 2.12.3, **not** 2.9.0: 2.9.0 requires `pydantic-core==2.23.2`, which publishes no
    cp314 wheel and fails to build from source on Python 3.14. 2.12.3 is the lowest version with
    cp314 support. The Python 3.14 platform constraint wins over the original pin.
- **Virtualenv:** `backend/.venv` (already covered by `.gitignore`). Run tests as
  `cd backend && .venv/bin/python -m pytest`.
- **Relational store is SQLite.** All primary keys are `String(36)` holding UUID strings — never a native UUID type. All array/object columns use `JSON`.
- **Password hashing calls `bcrypt` directly**, never `passlib` (Python 3.14 incompatibility).
- **Import rule:** `app/ai/` must never import from `app/api/`. `app/api/` must never import `app/ai/graph/` directly (Phase 1 adds `app/ai/graph/runner.py` as the only entry point).
- **Timezone rule:** all datetimes are stored UTC-naive (SQLite has no tzinfo). Always construct with `datetime.now(timezone.utc)` and re-tag naive values with `.replace(tzinfo=timezone.utc)` before arithmetic.
- **One `gen_uuid`.** v1 redefined it in every model file. It lives in `app/db/base.py` and is imported everywhere.
- **Commit messages carry no `Co-Authored-By` trailer.** The repository owner asked for none.
- **Out of scope for Phase 0:** any LangGraph, LangChain, RAG or LLM code. Phase 0 must not add those dependencies.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/requirements.txt` | Phase 0 dependency set (no AI packages yet) |
| `backend/pytest.ini` | pytest config, asyncio mode |
| `backend/app/config.py` | `Settings` via pydantic-settings; single source of env config |
| `backend/app/db/base.py` | `Base` declarative class, `gen_uuid()`, `utcnow()` |
| `backend/app/db/session.py` | engine, `SessionLocal`, `get_db()` dependency |
| `backend/app/db/models/core.py` | Tenant, User, Department, Contractor |
| `backend/app/db/models/complaint.py` | Complaint, ComplaintMedia |
| `backend/app/db/models/workflow.py` | WorkOrder, Escalation, Notification, DailyBriefing |
| `backend/app/db/models/ai.py` | AgentRun, AgentStep, RetrievedChunk, Document, DocumentChunk |
| `backend/app/db/models/evaluation.py` | EvalRun, EvalResult |
| `backend/app/evals/baseline.py` | ported v1 keyword classifier — the "before" column |
| `backend/app/constants.py` | `Category` enum, `RiskLevel` enum, category→department map |
| `backend/app/services/seed.py` | idempotent seed data, consistent with `constants.py` |
| `backend/app/main.py` | FastAPI app, `/health`, static uploads mount |
| `backend/alembic/versions/0001_baseline.py` | one baseline migration for all tables |
| `backend/tests/` | mirrors `app/` structure |

---

## Task 1: Reset the backend and preserve the keyword baseline

Deletes v1 and stands up the new package with configuration and the one piece of v1 worth keeping.

**Files:**
- Delete: `backend/app/` (entire v1 tree), `backend/backfill_complaints.py`, `backend/requirements_sqlite.txt`
- Create: `backend/requirements.txt`, `backend/pytest.ini`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/constants.py`, `backend/app/evals/__init__.py`, `backend/app/evals/baseline.py`
- Test: `backend/tests/__init__.py`, `backend/tests/test_config.py`, `backend/tests/evals/test_baseline.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `app.config.settings` — a `Settings` instance with `database_url: str`, `gemini_api_key: str | None`, `ollama_base_url: str`, `upload_dir: str`, `secret_key: str`, `otp_expire_minutes: int`
  - `app.constants.Category` — `StrEnum` with the 12 categories
  - `app.constants.RiskLevel` — `StrEnum`: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`
  - `app.constants.CATEGORY_DEPARTMENT` — `dict[Category, str]`
  - `app.evals.baseline.keyword_classify(text: str) -> BaselineResult` where `BaselineResult` is a dataclass with `category: Category`, `confidence: float`

- [ ] **Step 1: Delete the v1 backend**

v1 is fully documented in `docs/01-legacy-system-explained.md` and preserved in git history at commit `eff000d`. Nothing here is recoverable-only-from-disk.

```bash
cd /home/martin/Projects/CivicAi
git rm -r --quiet backend/app
git rm --quiet backend/backfill_complaints.py backend/requirements_sqlite.txt
git rm -r --quiet backend/alembic/versions 2>/dev/null || true
ls backend/
```

Expected: `Dockerfile`, `alembic/`, `alembic.ini`, `requirements.txt`, `.env.example`, and possibly `uploads/` remain.

- [ ] **Step 2: Write the new dependency set**

Phase 0 deliberately contains no AI packages. They arrive in Phase 1.

```bash
cat > backend/requirements.txt <<'EOF'
# ── Web ────────────────────────────────────────────
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9
aiofiles==24.1.0

# ── Database ───────────────────────────────────────
sqlalchemy==2.0.35
alembic==1.13.2

# ── Config & validation ────────────────────────────
pydantic==2.9.0
pydantic-settings==2.5.0
python-dotenv==1.0.1

# ── Auth ───────────────────────────────────────────
python-jose[cryptography]==3.3.0
bcrypt>=4.0.0

# ── Infrastructure ─────────────────────────────────
apscheduler==3.10.4
httpx==0.27.0

# ── Testing ────────────────────────────────────────
pytest==8.3.3
pytest-asyncio==0.24.0
EOF

cat > backend/pytest.ini <<'EOF'
[pytest]
testpaths = tests
asyncio_mode = auto
filterwarnings =
    ignore::DeprecationWarning
EOF
```

- [ ] **Step 3: Write the failing test for config and constants**

```bash
mkdir -p backend/app/evals backend/tests/evals
touch backend/app/__init__.py backend/app/evals/__init__.py
touch backend/tests/__init__.py backend/tests/evals/__init__.py
```

`backend/tests/test_config.py`:

```python
from app.config import Settings
from app.constants import Category, RiskLevel, CATEGORY_DEPARTMENT


def test_settings_have_sqlite_default():
    s = Settings(_env_file=None)
    assert s.database_url.startswith("sqlite")


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    s = Settings(_env_file=None)
    assert s.gemini_api_key == "test-key-123"


def test_there_are_twelve_categories():
    assert len(Category) == 12
    assert Category.ROADS == "ROADS"


def test_risk_levels_are_ordered_bands():
    assert [r.value for r in RiskLevel] == ["critical", "high", "medium", "low"]


def test_every_category_maps_to_a_department():
    """v1 Bug 3: two categories mapped to departments that did not exist."""
    for category in Category:
        assert category in CATEGORY_DEPARTMENT, f"{category} has no department"
        assert CATEGORY_DEPARTMENT[category], f"{category} maps to an empty name"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 5: Implement config and constants**

`backend/app/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All environment configuration. Read once, imported everywhere."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ──────────────────────────────────────────────
    database_url: str = "sqlite:///./civicai.db"

    # ── Auth ──────────────────────────────────────────────────
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    otp_expire_minutes: int = 10

    # ── LLM providers (used from Phase 1 onward) ──────────────
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # ── Email ─────────────────────────────────────────────────
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""

    # ── Storage ───────────────────────────────────────────────
    upload_dir: str = "./uploads"


settings = Settings()
```

`backend/app/constants.py`:

```python
"""Domain vocabulary shared across the application.

v1 scattered these values across four modules and a seed script, which is how
two categories ended up mapped to departments that were never created. There is
one definition of each here, and `tests/test_config.py` asserts they agree.
"""

from enum import StrEnum


class Category(StrEnum):
    ROADS = "ROADS"
    ELECTRICITY = "ELECTRICITY"
    WATER = "WATER"
    SANITATION = "SANITATION"
    PUBLIC_SPACES = "PUBLIC_SPACES"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    FLOODING = "FLOODING"
    FIRE_HAZARD = "FIRE_HAZARD"
    CONSTRUCTION = "CONSTRUCTION"
    STRAY_ANIMALS = "STRAY_ANIMALS"
    SEWAGE = "SEWAGE"


class RiskLevel(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Every Category MUST appear here, and every department named here MUST be
# created by app/services/seed.py. Both invariants are tested.
CATEGORY_DEPARTMENT: dict[Category, str] = {
    Category.ROADS: "Public Works Department",
    Category.CONSTRUCTION: "Public Works Department",
    Category.ELECTRICITY: "Electricity Board",
    Category.WATER: "Water Supply Department",
    Category.SANITATION: "Sanitation Department",
    Category.SEWAGE: "Sanitation Department",
    Category.PUBLIC_SPACES: "Parks & Recreation",
    Category.EDUCATION: "Education Department",
    Category.HEALTH: "Health Department",
    Category.FLOODING: "Flood Control Authority",
    Category.FIRE_HAZARD: "Fire Department",
    Category.STRAY_ANIMALS: "Animal Control",
}
```

Note the fix: `CONSTRUCTION` and `SEWAGE` now point at departments the seed actually creates, rather than v1's phantom "Building & Construction Authority" and "Sewage & Drainage Board".

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 7: Write the failing test for the ported baseline classifier**

`backend/tests/evals/test_baseline.py`:

```python
from app.constants import Category
from app.evals.baseline import keyword_classify


def test_classifies_an_obvious_pothole():
    result = keyword_classify("There is a huge pothole on the main road near the market")
    assert result.category == Category.ROADS
    assert result.confidence > 0.5


def test_classifies_a_streetlight_fault():
    result = keyword_classify("The streetlight pole has hanging wires, no power since Monday")
    assert result.category == Category.ELECTRICITY


def test_unmatched_text_gets_low_confidence():
    result = keyword_classify("zzzz qqqq wwww")
    assert result.confidence <= 0.4


def test_confidence_is_always_a_float_between_zero_and_one():
    """v1 compared confidence with `< 0.7` without guaranteeing it was numeric."""
    for text in ["pothole road street", "", "fire gas leak smoke burning spark"]:
        result = keyword_classify(text)
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0


def test_returns_a_real_category_enum_member():
    result = keyword_classify("garbage overflowing from the dustbin")
    assert isinstance(result.category, Category)
```

- [ ] **Step 8: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/evals/test_baseline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.evals.baseline'`

- [ ] **Step 9: Port the v1 keyword classifier**

`backend/app/evals/baseline.py`:

```python
"""The v1 keyword classifier, preserved as the naive baseline for evaluation.

This is the only code carried forward from CivicAI v1. It exists so every
accuracy number the eval harness reports in Phase 3 has a "before" column to be
measured against. It is NOT used in the production path.

Original: backend/app/services/llm.py :: _keyword_classify (v1).
"""

from dataclasses import dataclass

from app.constants import Category


@dataclass(frozen=True)
class BaselineResult:
    category: Category
    confidence: float


_KEYWORD_MAP: list[tuple[Category, list[str]]] = [
    (Category.ROADS, ["road", "pothole", "street", "highway", "pavement",
                      "footpath", "divider", "crack", "tar", "asphalt", "traffic"]),
    (Category.ELECTRICITY, ["electricity", "electric", "power", "light", "streetlight",
                            "wire", "transformer", "outage", "voltage", "bulb", "pole"]),
    (Category.WATER, ["water", "pipe", "supply", "leakage", "leak", "contamination",
                      "drinking", "tap", "borewell", "drainage"]),
    (Category.SEWAGE, ["sewage", "sewer", "manhole", "drain overflow", "septic",
                       "gutter", "blockage", "overflow"]),
    (Category.SANITATION, ["garbage", "waste", "trash", "dustbin", "bin", "litter",
                           "sanitation", "cleaning", "sweep"]),
    (Category.FLOODING, ["flood", "waterlog", "waterlogging", "inundation", "drain",
                         "stagnant water", "rain water"]),
    (Category.FIRE_HAZARD, ["fire", "gas leak", "smoke", "burning", "spark", "hazard",
                            "flammable", "explosion"]),
    (Category.HEALTH, ["hospital", "ambulance", "clinic", "health", "medical",
                       "medicine", "patient", "doctor"]),
    (Category.PUBLIC_SPACES, ["park", "tree", "garden", "bench", "playground",
                              "footpath", "public", "fallen tree"]),
    (Category.EDUCATION, ["school", "college", "education", "classroom", "student",
                          "toilet", "restroom", "building"]),
    (Category.CONSTRUCTION, ["construction", "illegal", "excavation", "digging",
                             "building", "demolish", "encroach"]),
    (Category.STRAY_ANIMALS, ["dog", "stray", "animal", "cattle", "cow", "buffalo",
                              "horse", "bite", "aggressive"]),
]


def keyword_classify(text: str) -> BaselineResult:
    """Count keyword hits per category and take the argmax.

    Confidence is fabricated from the hit count, exactly as v1 did. That is the
    point: this is the weak baseline the LLM pipeline has to beat.
    """
    lowered = (text or "").lower()
    best_category, best_score = Category.ROADS, 0

    for category, keywords in _KEYWORD_MAP:
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best_score:
            best_score, best_category = score, category

    confidence = min(0.5 + best_score * 0.1, 0.9) if best_score > 0 else 0.4
    return BaselineResult(category=best_category, confidence=float(confidence))
```

- [ ] **Step 10: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/evals/test_baseline.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 11: Run the whole suite and commit**

Run: `cd backend && python -m pytest -v`
Expected: PASS, 10 tests total.

```bash
cd /home/martin/Projects/CivicAi
git add -A backend/
git commit -m "feat: reset backend to v2 foundation

Delete the v1 application tree (documented in docs/01-legacy-system-explained.md,
preserved at commit eff000d). Add Phase 0 dependencies, pydantic-settings config,
and shared domain constants.

Port the v1 keyword classifier to app/evals/baseline.py as the naive baseline
for Phase 3 evaluation — the only v1 code carried forward.

Fixes v1 Bug 3 by construction: CATEGORY_DEPARTMENT now maps CONSTRUCTION and
SEWAGE to departments that are actually seeded, with a test enforcing it."
```

---

## Task 2: Database layer and core domain models

**Files:**
- Create: `backend/app/db/__init__.py`, `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/app/db/models/__init__.py`, `backend/app/db/models/core.py`
- Test: `backend/tests/db/__init__.py`, `backend/tests/conftest.py`, `backend/tests/db/test_core_models.py`

**Interfaces:**
- Consumes: `app.config.settings`, `app.constants.Category`
- Produces:
  - `app.db.base.Base` — SQLAlchemy `DeclarativeBase` subclass
  - `app.db.base.gen_uuid() -> str`
  - `app.db.base.utcnow() -> datetime` (timezone-aware UTC)
  - `app.db.session.engine`, `app.db.session.SessionLocal`, `app.db.session.get_db()` generator
  - `app.db.models.core.Tenant` (`id`, `name`, `config`, `created_at`)
  - `app.db.models.core.User` (`id`, `tenant_id`, `email`, `name`, `phone`, `role`, `password_hash`, `created_at`)
    - Note: v1's `User.department_id` is deliberately **not** carried over. Together with
      `Department.head_officer_id` it formed a circular foreign key, which `Base.metadata.create_all`
      cannot order and SQLite cannot repair with `ALTER TABLE ADD CONSTRAINT`. v1 declared the column
      and never read it. Officers link to departments through `Department.head_officer_id` only.
  - `app.db.models.core.Department` (`id`, `tenant_id`, `name`, `categories: list`, `head_officer_id`, `created_at`)
  - `app.db.models.core.Contractor` (`id`, `tenant_id`, `name`, `specializations: list`, `rating: float`, `active_workload: int`, `zone`, `phone`, `created_at`)
  - `tests/conftest.py::db_session` — a pytest fixture yielding a `Session` on an in-memory SQLite database

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p backend/app/db/models backend/tests/db
touch backend/app/db/__init__.py backend/app/db/models/__init__.py backend/tests/db/__init__.py
```

`backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models  # noqa: F401 — registers every model on Base.metadata


@pytest.fixture
def db_session():
    """A fresh in-memory database per test. No file, no cleanup, no shared state."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
```

`backend/tests/db/test_core_models.py`:

```python
from app.constants import Category
from app.db.models.core import Contractor, Department, Tenant, User


def test_tenant_gets_a_uuid_string_primary_key(db_session):
    tenant = Tenant(name="Bangalore Municipal Corporation")
    db_session.add(tenant)
    db_session.commit()

    assert isinstance(tenant.id, str)
    assert len(tenant.id) == 36


def test_department_stores_categories_as_json(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.flush()

    dept = Department(
        tenant_id=tenant.id,
        name="Public Works Department",
        categories=[Category.ROADS.value, Category.CONSTRUCTION.value],
    )
    db_session.add(dept)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.query(Department).one()
    assert reloaded.categories == ["ROADS", "CONSTRUCTION"]


def test_contractor_defaults_are_sane(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.flush()

    contractor = Contractor(tenant_id=tenant.id, name="RoadFix India")
    db_session.add(contractor)
    db_session.commit()

    assert contractor.rating == 0.0
    assert contractor.active_workload == 0


def test_user_role_defaults_to_citizen(db_session):
    user = User(email="a@b.com", name="A")
    db_session.add(user)
    db_session.commit()
    assert user.role == "citizen"


def test_user_and_department_have_no_circular_foreign_key():
    """create_all cannot order a cycle, and SQLite cannot repair one afterwards."""
    assert not hasattr(User, "department_id")


def test_created_at_is_populated_automatically(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.commit()
    assert tenant.created_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/db/test_core_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.base'`

- [ ] **Step 3: Implement the declarative base**

`backend/app/db/base.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def gen_uuid() -> str:
    """UUID as a 36-char string. SQLite has no native UUID type."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    SQLite drops tzinfo on write, so values read back are naive. Anything doing
    arithmetic on a stored datetime must re-tag it with timezone.utc first.
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 4: Implement the session module**

`backend/app/db/session.py`:

```python
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# check_same_thread=False is required because FastAPI serves requests from a
# thread pool and SQLite otherwise refuses cross-thread connection reuse.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 5: Implement the core models**

`backend/app/db/models/core.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    departments: Mapped[list["Department"]] = relationship(back_populates="tenant")
    contractors: Mapped[list["Contractor"]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="citizen")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # No department_id: it would close a User <-> Department foreign-key cycle that
    # create_all cannot order and SQLite cannot fix with ALTER TABLE. v1 had the
    # column and never read it. Department.head_officer_id carries this link.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="users")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Categories this department owns. Read by the routing node in Phase 1 —
    # v1 declared this column and then hardcoded the mapping in Python instead.
    categories: Mapped[list | None] = mapped_column(JSON, default=list)
    head_officer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="departments")


class Contractor(Base):
    __tablename__ = "contractors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specializations: Mapped[list | None] = mapped_column(JSON, default=list)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    active_workload: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    zone: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="contractors")
```

`backend/app/db/models/__init__.py`:

```python
"""Importing this package registers every model on Base.metadata.

Alembic autogenerate and Base.metadata.create_all both depend on it, so any new
model module must be added here.
"""

from app.db.models.core import Contractor, Department, Tenant, User

__all__ = ["Contractor", "Department", "Tenant", "User"]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/db/test_core_models.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 7: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/db backend/tests
git commit -m "feat: add database layer and core domain models

Single gen_uuid() and utcnow() in db/base.py rather than v1's per-file
redefinition. Department.categories is now the authoritative category mapping
and will be read by the routing node instead of a hardcoded dict."
```

---

## Task 3: Complaint and workflow models

**Files:**
- Create: `backend/app/db/models/complaint.py`, `backend/app/db/models/workflow.py`
- Modify: `backend/app/db/models/__init__.py`
- Test: `backend/tests/db/test_complaint_models.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `app.db.models.core.Tenant`
- Produces:
  - `app.db.models.complaint.Complaint` — includes v2 fields `graph_thread_id: str | None`, `pipeline_version: str | None`, `evidence: list | None`, and `terminal_reason: str | None`
  - `app.db.models.complaint.ComplaintMedia`
  - `app.db.models.workflow.WorkOrder` — includes `is_cluster: bool` (v1 used a `LIKE '%[CLUSTER]%'` query on a free-text notes column)
  - `app.db.models.workflow.Escalation`, `Notification`, `DailyBriefing`
  - `Notification.dedupe_key: str | None` — unique per complaint+type+bucket, fixing v1 Bug 4

- [ ] **Step 1: Write the failing test**

`backend/tests/db/test_complaint_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Tenant
from app.db.models.workflow import Escalation, Notification, WorkOrder


def _tenant(db_session):
    tenant = Tenant(name="BMC")
    db_session.add(tenant)
    db_session.flush()
    return tenant


def test_complaint_requires_a_tracking_id(db_session):
    complaint = Complaint(
        tracking_id="CIV-ABC12345",
        citizen_email="a@b.com",
        description="Pothole on the main road",
    )
    db_session.add(complaint)
    db_session.commit()
    assert complaint.status == "submitted"
    assert complaint.reopen_count == 0


def test_tracking_id_is_unique(db_session):
    for _ in range(2):
        db_session.add(Complaint(
            tracking_id="CIV-DUPLICATE",
            citizen_email="a@b.com",
            description="x" * 20,
        ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_complaint_carries_graph_metadata(db_session):
    complaint = Complaint(
        tracking_id="CIV-GRAPH001",
        citizen_email="a@b.com",
        description="Streetlight is out",
        graph_thread_id="thread-abc",
        pipeline_version="v2.0",
        evidence=[{"source": "sop_roads.md", "score": 0.81}],
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.query(Complaint).one()
    assert reloaded.graph_thread_id == "thread-abc"
    assert reloaded.evidence[0]["source"] == "sop_roads.md"


def test_media_links_back_to_its_complaint(db_session):
    complaint = Complaint(
        tracking_id="CIV-MEDIA001",
        citizen_email="a@b.com",
        description="Broken bench in the park",
    )
    db_session.add(complaint)
    db_session.flush()
    db_session.add(ComplaintMedia(
        complaint_id=complaint.id,
        file_path="uploads/x.jpg",
        media_type="image",
    ))
    db_session.commit()
    db_session.expire_all()

    assert len(db_session.query(Complaint).one().media) == 1


def test_work_order_flags_clusters_with_a_boolean(db_session):
    """v1 detected clusters with a LIKE query against a free-text notes column."""
    complaint = Complaint(
        tracking_id="CIV-WO000001",
        citizen_email="a@b.com",
        description="Waterlogging near the junction",
    )
    db_session.add(complaint)
    db_session.flush()

    order = WorkOrder(complaint_id=complaint.id, is_cluster=True)
    db_session.add(order)
    db_session.commit()

    assert order.status == "created"
    assert order.is_cluster is True


def test_notification_dedupe_key_is_unique(db_session):
    """v1 Bug 4: SLA warnings re-sent every 5 minutes with no idempotency key."""
    for _ in range(2):
        db_session.add(Notification(
            recipient_email="a@b.com",
            notification_type="sla_warning",
            message="SLA approaching",
            dedupe_key="complaint-1:sla_warning:50",
        ))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_escalation_records_the_jurisdiction_hop(db_session):
    complaint = Complaint(
        tracking_id="CIV-ESC00001",
        citizen_email="a@b.com",
        description="Open manhole outside the school",
    )
    db_session.add(complaint)
    db_session.flush()

    db_session.add(Escalation(
        complaint_id=complaint.id,
        from_level="ward",
        to_level="block",
        reason="SLA breached",
    ))
    db_session.commit()
    assert db_session.query(Escalation).one().to_level == "block"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/db/test_complaint_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.complaint'`

- [ ] **Step 3: Implement the complaint models**

`backend/app/db/models/complaint.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    # ── citizen ───────────────────────────────────────────────
    citizen_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    citizen_phone: Mapped[str | None] = mapped_column(String(50))
    citizen_name: Mapped[str | None] = mapped_column(String(255))

    # ── content ───────────────────────────────────────────────
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted", index=True)
    # Why a complaint stopped. v1 folded rejections into an errors list, which is
    # how AI-rejected complaints ended up indistinguishable from unprocessed ones.
    terminal_reason: Mapped[str | None] = mapped_column(String(255))

    # ── AI results ────────────────────────────────────────────
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(100))
    priority_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[list | None] = mapped_column(JSON, default=list)

    # ── graph metadata ────────────────────────────────────────
    graph_thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(20))

    # ── location ──────────────────────────────────────────────
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(500))
    ward: Mapped[str | None] = mapped_column(String(100))
    block: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    state: Mapped[str | None] = mapped_column(String(100))

    # ── citizen feedback ──────────────────────────────────────
    satisfaction_rating: Mapped[int | None] = mapped_column(Integer)
    satisfaction_comment: Mapped[str | None] = mapped_column(Text)
    verified_fixed: Mapped[bool | None] = mapped_column(Boolean)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── officer email flow ────────────────────────────────────
    email_draft: Mapped[str | None] = mapped_column(Text)
    email_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    media: Mapped[list["ComplaintMedia"]] = relationship(back_populates="complaint")
    work_order: Mapped["WorkOrder | None"] = relationship(back_populates="complaint", uselist=False)
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="complaint")


class ComplaintMedia(Base):
    __tablename__ = "complaint_media"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    complaint: Mapped["Complaint"] = relationship(back_populates="media")
```

- [ ] **Step 4: Implement the workflow models**

`backend/app/db/models/workflow.py`:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    contractor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("contractors.id"))
    officer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created", index=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    # Where the cost estimate came from, so the UI can cite it. v1 used a
    # hardcoded per-category dict and recorded nothing.
    cost_basis: Mapped[str | None] = mapped_column(Text)
    materials: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # v1 identified cluster orders with `notes LIKE '%[CLUSTER]%'`.
    is_cluster: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cluster_size: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completion_photo: Mapped[str | None] = mapped_column(String(500))

    complaint: Mapped["Complaint"] = relationship(back_populates="work_order")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str] = mapped_column(String(36), ForeignKey("complaints.id"), nullable=False)
    from_level: Mapped[str] = mapped_column(String(50), nullable=False)
    to_level: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    escalated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    complaint: Mapped["Complaint"] = relationship(back_populates="escalations")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("complaints.id"))
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Idempotency guard. v1 re-sent SLA warnings every 5 minutes because nothing
    # recorded that a given warning had already gone out.
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tenants.id"))
    brief_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    new_complaints: Mapped[int] = mapped_column(Integer, default=0)
    resolved_today: Mapped[int] = mapped_column(Integer, default=0)
    sla_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    escalations_today: Mapped[int] = mapped_column(Integer, default=0)
    clusters_detected: Mapped[int] = mapped_column(Integer, default=0)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    # False when the LLM path failed and template text was used instead. v1 served
    # fallback text for its entire life without recording that it had.
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

- [ ] **Step 5: Register the new models**

Replace `backend/app/db/models/__init__.py` with:

```python
"""Importing this package registers every model on Base.metadata.

Alembic autogenerate and Base.metadata.create_all both depend on it, so any new
model module must be added here.
"""

from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Contractor, Department, Tenant, User
from app.db.models.workflow import DailyBriefing, Escalation, Notification, WorkOrder

__all__ = [
    "Complaint", "ComplaintMedia",
    "Contractor", "Department", "Tenant", "User",
    "DailyBriefing", "Escalation", "Notification", "WorkOrder",
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/db -v`
Expected: PASS, 13 tests.

- [ ] **Step 7: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/db backend/tests
git commit -m "feat: add complaint and workflow models

Adds v2 fields: graph_thread_id, pipeline_version, evidence citations, and
terminal_reason so a rejection is distinguishable from a crash.

Structural fixes for two v1 bugs: WorkOrder.is_cluster replaces a
'notes LIKE %[CLUSTER]%' query, and Notification.dedupe_key gives SLA warnings
an idempotency guard."
```

---

## Task 4: AI observability and evaluation tables

**Files:**
- Create: `backend/app/db/models/ai.py`, `backend/app/db/models/evaluation.py`
- Modify: `backend/app/db/models/__init__.py`
- Test: `backend/tests/db/test_ai_models.py`

**Interfaces:**
- Consumes: `app.db.base.Base`
- Produces:
  - `AgentRun` (`id`, `complaint_id`, `thread_id`, `status`, `graph_version`, `started_at`, `finished_at`, `duration_ms`, `total_tokens`, `estimated_cost`, `langsmith_url`, `error`)
  - `AgentStep` (`id`, `run_id`, `seq`, `node`, `status`, `duration_ms`, `tokens`, `input_summary`, `output_summary`, `error`)
  - `RetrievedChunk` (`id`, `run_id`, `node`, `source`, `chunk_id`, `score`, `snippet`)
  - `Document` (`id`, `collection`, `source_path`, `title`, `content_hash`, `chunk_count`, `embedding_model`, `indexed_at`)
  - `DocumentChunk` (`id`, `document_id`, `seq`, `text`, `metadata_json`)
  - `EvalRun` (`id`, `suite`, `dataset_name`, `dataset_hash`, `git_sha`, `config_label`, `started_at`, `finished_at`)
  - `EvalResult` (`id`, `eval_run_id`, `metric`, `value`, `detail_json`)

- [ ] **Step 1: Write the failing test**

`backend/tests/db/test_ai_models.py`:

```python
from app.db.models.ai import AgentRun, AgentStep, Document, DocumentChunk, RetrievedChunk
from app.db.models.evaluation import EvalResult, EvalRun


def test_agent_run_records_cost_and_trace_url(db_session):
    run = AgentRun(
        thread_id="thread-1",
        status="completed",
        graph_version="v2.0",
        duration_ms=4200,
        total_tokens=1850,
        estimated_cost=0.0021,
        langsmith_url="https://smith.langchain.com/o/x/r/y",
    )
    db_session.add(run)
    db_session.commit()

    assert run.status == "completed"
    assert run.estimated_cost == 0.0021


def test_steps_are_ordered_by_seq_within_a_run(db_session):
    run = AgentRun(thread_id="thread-2", status="running")
    db_session.add(run)
    db_session.flush()

    for seq, node in enumerate(["intake", "validate", "classify"]):
        db_session.add(AgentStep(run_id=run.id, seq=seq, node=node, status="ok"))
    db_session.commit()
    db_session.expire_all()

    steps = db_session.query(AgentStep).order_by(AgentStep.seq).all()
    assert [s.node for s in steps] == ["intake", "validate", "classify"]


def test_retrieved_chunk_records_its_score(db_session):
    run = AgentRun(thread_id="thread-3", status="completed")
    db_session.add(run)
    db_session.flush()

    db_session.add(RetrievedChunk(
        run_id=run.id, node="route", source="sop_public_works.md",
        chunk_id="c-17", score=0.83, snippet="Potholes are repaired within...",
    ))
    db_session.commit()
    assert db_session.query(RetrievedChunk).one().score == 0.83


def test_document_tracks_its_embedding_model(db_session):
    """Querying an index built by a different embedding model must be detectable."""
    doc = Document(
        collection="policy",
        source_path="corpus/sla_policy.md",
        title="SLA Policy Handbook",
        content_hash="abc123",
        chunk_count=14,
        embedding_model="gemini-embedding-001@768",
    )
    db_session.add(doc)
    db_session.flush()
    db_session.add(DocumentChunk(document_id=doc.id, seq=0, text="Priority bands..."))
    db_session.commit()

    assert db_session.query(Document).one().embedding_model.endswith("@768")


def test_eval_results_attach_to_a_run(db_session):
    run = EvalRun(suite="core", dataset_name="golden_complaints",
                  dataset_hash="deadbeef", git_sha="abc1234", config_label="v2_full")
    db_session.add(run)
    db_session.flush()

    db_session.add(EvalResult(eval_run_id=run.id, metric="category_macro_f1", value=0.91))
    db_session.commit()

    assert db_session.query(EvalResult).one().metric == "category_macro_f1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/db/test_ai_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.ai'`

- [ ] **Step 3: Implement the AI tables**

`backend/app/db/models/ai.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class AgentRun(Base):
    """One execution of the complaint graph.

    Persisted alongside LangSmith so the in-app trace viewer works offline and
    without an account.
    """

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    complaint_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("complaints.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    graph_version: Mapped[str | None] = mapped_column(String(20))

    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    langsmith_url: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)

    steps: Mapped[list["AgentStep"]] = relationship(back_populates="run")
    chunks: Mapped[list["RetrievedChunk"]] = relationship(back_populates="run")


class AgentStep(Base):
    """One node execution within a run."""

    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    tokens: Mapped[int | None] = mapped_column(Integer)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped["AgentRun"] = relationship(back_populates="steps")


class RetrievedChunk(Base):
    """A retrieval hit, recorded so any AI decision can show its sources."""

    __tablename__ = "retrieved_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    node: Mapped[str] = mapped_column(String(60), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[float | None] = mapped_column(Float)
    snippet: Mapped[str | None] = mapped_column(Text)

    run: Mapped["AgentRun"] = relationship(back_populates="chunks")


class Document(Base):
    """A source document in the RAG corpus."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    collection: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # "policy" | "cases"
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    # "<model>@<dimensions>". Querying an index built by a different model must fail loudly.
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped["Document"] = relationship(back_populates="chunks")
```

`backend/app/db/models/evaluation.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, utcnow


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    suite: Mapped[str] = mapped_column(String(40), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(80), nullable=False)
    dataset_hash: Mapped[str | None] = mapped_column(String(64))
    git_sha: Mapped[str | None] = mapped_column(String(40))
    # Which configuration produced these numbers: "baseline_keyword",
    # "llm_no_rag" or "v2_full". This is what makes the comparison table possible.
    config_label: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    results: Mapped[list["EvalResult"]] = relationship(back_populates="eval_run")


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    eval_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    detail_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    eval_run: Mapped["EvalRun"] = relationship(back_populates="results")
```

- [ ] **Step 4: Register the new models**

Replace `backend/app/db/models/__init__.py` with:

```python
"""Importing this package registers every model on Base.metadata.

Alembic autogenerate and Base.metadata.create_all both depend on it, so any new
model module must be added here.
"""

from app.db.models.ai import (
    AgentRun, AgentStep, Document, DocumentChunk, RetrievedChunk,
)
from app.db.models.complaint import Complaint, ComplaintMedia
from app.db.models.core import Contractor, Department, Tenant, User
from app.db.models.evaluation import EvalResult, EvalRun
from app.db.models.workflow import DailyBriefing, Escalation, Notification, WorkOrder

__all__ = [
    "AgentRun", "AgentStep", "Document", "DocumentChunk", "RetrievedChunk",
    "Complaint", "ComplaintMedia",
    "Contractor", "Department", "Tenant", "User",
    "EvalResult", "EvalRun",
    "DailyBriefing", "Escalation", "Notification", "WorkOrder",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/db -v`
Expected: PASS, 18 tests.

- [ ] **Step 6: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/db backend/tests
git commit -m "feat: add AI observability and evaluation tables

agent_runs, agent_steps and retrieved_chunks back the in-app trace viewer so it
works without a LangSmith account. documents/document_chunks record which
embedding model built an index. eval_runs.config_label is what makes the
baseline-vs-v2 comparison table possible."
```

---

## Task 5: Alembic baseline migration and seed data

**Files:**
- Create: `backend/app/services/__init__.py`, `backend/app/services/seed.py`
- Modify: `backend/alembic/env.py`, `backend/alembic.ini`
- Test: `backend/tests/services/__init__.py`, `backend/tests/services/test_seed.py`, `backend/tests/db/test_migrations.py`

**Interfaces:**
- Consumes: `app.db.base.Base`, `app.db.models` (all), `app.constants.CATEGORY_DEPARTMENT`
- Produces:
  - `app.services.seed.seed_database(db: Session) -> dict` — idempotent; returns `{"message": str, "tenant_id": str}`
  - Alembic revision `0001_baseline` creating every table

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p backend/tests/services && touch backend/tests/services/__init__.py
```

`backend/tests/services/test_seed.py`:

```python
from app.constants import CATEGORY_DEPARTMENT, Category
from app.db.models.core import Contractor, Department, Tenant, User
from app.services.seed import seed_database


def test_seed_creates_a_tenant_admin_departments_and_contractors(db_session):
    result = seed_database(db_session)

    assert result["tenant_id"]
    assert db_session.query(Tenant).count() == 1
    assert db_session.query(User).filter(User.role == "admin").count() == 1
    assert db_session.query(Department).count() > 0
    assert db_session.query(Contractor).count() > 0


def test_seed_is_idempotent(db_session):
    seed_database(db_session)
    before = db_session.query(Department).count()
    seed_database(db_session)
    assert db_session.query(Department).count() == before


def test_every_mapped_department_actually_exists(db_session):
    """v1 Bug 3: CONSTRUCTION and SEWAGE mapped to departments never seeded."""
    seed_database(db_session)
    seeded_names = {d.name for d in db_session.query(Department).all()}

    for category, dept_name in CATEGORY_DEPARTMENT.items():
        assert dept_name in seeded_names, f"{category} maps to unseeded '{dept_name}'"


def test_every_category_is_claimed_by_exactly_one_department(db_session):
    seed_database(db_session)
    claimed: list[str] = []
    for dept in db_session.query(Department).all():
        claimed.extend(dept.categories or [])

    assert sorted(claimed) == sorted(c.value for c in Category)


def test_admin_password_is_hashed_not_stored_plain(db_session):
    seed_database(db_session)
    admin = db_session.query(User).filter(User.role == "admin").one()
    assert admin.password_hash
    assert "admin123" not in admin.password_hash
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/services/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.seed'`

- [ ] **Step 3: Implement the seed service**

```bash
mkdir -p backend/app/services && touch backend/app/services/__init__.py
```

`backend/app/services/seed.py`:

```python
"""Idempotent development seed data.

Departments are derived from app.constants.CATEGORY_DEPARTMENT rather than a
separate hand-written list. v1 kept the two in parallel and they drifted, which
left CONSTRUCTION and SEWAGE pointing at departments that were never created.
"""

import bcrypt
from sqlalchemy.orm import Session

from app.constants import CATEGORY_DEPARTMENT, Category
from app.db.models.core import Contractor, Department, Tenant, User

_OFFICER_NAMES = {
    "Public Works Department": "Officer Ramesh",
    "Electricity Board": "Officer Priya",
    "Water Supply Department": "Officer Kumar",
    "Sanitation Department": "Officer Lakshmi",
    "Parks & Recreation": "Officer Suresh",
    "Health Department": "Officer Meera",
    "Fire Department": "Officer Vijay",
    "Flood Control Authority": "Officer Anita",
    "Animal Control": "Officer Raj",
    "Education Department": "Officer Deepa",
}

_CONTRACTORS: list[tuple[str, list[Category], float, str, int]] = [
    ("RoadFix India Pvt Ltd", [Category.ROADS, Category.CONSTRUCTION], 4.5, "South Bangalore", 2),
    ("PowerGrid Solutions", [Category.ELECTRICITY], 4.2, "North Bangalore", 1),
    ("AquaFlow Services", [Category.WATER, Category.SEWAGE, Category.FLOODING], 4.0, "East Bangalore", 3),
    ("CleanCity Corp", [Category.SANITATION, Category.SEWAGE], 3.8, "West Bangalore", 2),
    ("GreenScape Pvt Ltd", [Category.PUBLIC_SPACES], 4.3, "Central Bangalore", 1),
    ("SafeGuard Services", [Category.FIRE_HAZARD, Category.ELECTRICITY], 4.6, "South Bangalore", 0),
    ("BuildRight Construction", [Category.ROADS, Category.CONSTRUCTION, Category.FLOODING], 4.1, "North Bangalore", 4),
    ("MediCare Infrastructure", [Category.HEALTH, Category.EDUCATION], 3.9, "East Bangalore", 1),
    ("PawCare Animal Services", [Category.STRAY_ANIMALS], 4.0, "Central Bangalore", 0),
]


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _departments_from_constants() -> dict[str, list[str]]:
    """Invert CATEGORY_DEPARTMENT into {department_name: [categories]}."""
    grouped: dict[str, list[str]] = {}
    for category, dept_name in CATEGORY_DEPARTMENT.items():
        grouped.setdefault(dept_name, []).append(category.value)
    return grouped


def seed_database(db: Session) -> dict:
    existing = db.query(Tenant).first()
    if existing:
        return {"message": "Database already seeded", "tenant_id": existing.id}

    tenant = Tenant(
        name="Bangalore Municipal Corporation",
        config={"sla_hours": {"critical": 4, "high": 24, "medium": 72, "low": 168}},
    )
    db.add(tenant)
    db.flush()

    db.add(User(
        tenant_id=tenant.id, email="admin@civicai.gov", name="System Admin",
        role="admin", password_hash=_hash("admin123"),
    ))

    for dept_name, categories in _departments_from_constants().items():
        officer_name = _OFFICER_NAMES.get(dept_name, f"Officer {dept_name.split()[0]}")
        officer = User(
            tenant_id=tenant.id,
            email=f"{officer_name.lower().replace(' ', '.')}@civicai.gov",
            name=officer_name, role="officer", password_hash=_hash("officer123"),
        )
        db.add(officer)
        db.flush()
        db.add(Department(
            tenant_id=tenant.id, name=dept_name,
            categories=sorted(categories), head_officer_id=officer.id,
        ))

    for name, specs, rating, zone, workload in _CONTRACTORS:
        db.add(Contractor(
            tenant_id=tenant.id, name=name,
            specializations=[c.value for c in specs],
            rating=rating, active_workload=workload, zone=zone,
        ))

    db.commit()
    return {"message": "Database seeded successfully", "tenant_id": tenant.id}
```

- [ ] **Step 4: Run the seed tests to verify they pass**

Run: `cd backend && python -m pytest tests/services/test_seed.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Point Alembic at the new metadata**

`backend/alembic/env.py` already sets the URL from settings at module level and already
assigns `target_metadata = Base.metadata`. The only broken part is the import of v1's
`app.database`. Make exactly this edit and nothing else.

Find these two lines near the top of `backend/alembic/env.py`:

```python
from app.config import settings
from app.database import Base
```

Replace them with:

```python
from app.config import settings
from app.db.base import Base
import app.db.models  # noqa: F401 — registers every model on Base.metadata
```

Do **not** add `config.set_main_option(...)` calls inside `run_migrations_online()` or
`run_migrations_offline()` — line 16 of the file already does it at module level, which
covers both modes. Leave `alembic.ini`'s `sqlalchemy.url` alone; it is overridden at
runtime.

Verify the edit:

```bash
cd backend && grep -n "app.db" alembic/env.py
```

Expected: two lines — the `from app.db.base import Base` import and the
`import app.db.models` registration.

- [ ] **Step 6: Generate the baseline migration**

```bash
cd backend
mkdir -p alembic/versions
python -m alembic revision --autogenerate -m "baseline schema" --rev-id 0001_baseline
```

Expected: creates `backend/alembic/versions/0001_baseline_baseline_schema.py`.

- [ ] **Step 7: Write the test that the migration matches the models**

`backend/tests/db/test_migrations.py`:

```python
import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "tenants", "users", "departments", "contractors",
    "complaints", "complaint_media",
    "work_orders", "escalations", "notifications", "daily_briefings",
    "agent_runs", "agent_steps", "retrieved_chunks", "documents", "document_chunks",
    "eval_runs", "eval_results",
}


def test_migration_creates_every_table(tmp_path):
    db_file = tmp_path / "migrated.db"
    result = subprocess.run(
        ["python", "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db_file}"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{db_file}")
    actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()

    missing = EXPECTED_TABLES - actual
    assert not missing, f"migration did not create: {sorted(missing)}"
```

- [ ] **Step 8: Run the migration test**

Run: `cd backend && python -m pytest tests/db/test_migrations.py -v`
Expected: PASS. If it fails with missing tables, a model module is not imported in `app/db/models/__init__.py` — add it and regenerate the migration.

- [ ] **Step 9: Commit**

```bash
cd /home/martin/Projects/CivicAi
git add backend/app/services backend/alembic backend/tests
git commit -m "feat: add Alembic baseline migration and seed data

Departments are derived from CATEGORY_DEPARTMENT rather than a parallel list,
so the v1 drift that left two categories pointing at nonexistent departments
cannot recur. Tests assert every category is claimed by exactly one seeded
department, and that the migration creates all 17 tables."
```

---

## Task 6: FastAPI application boot

**Files:**
- Create: `backend/app/main.py`, `backend/app/api/__init__.py`, `backend/app/api/system.py`
- Test: `backend/tests/api/__init__.py`, `backend/tests/api/test_health.py`, `backend/tests/test_import_rules.py`

**Interfaces:**
- Consumes: `app.config.settings`, `app.db.session.get_db`, `app.services.seed.seed_database`
- Produces:
  - `app.main.app` — the FastAPI instance
  - `GET /health` → `{"status": "ok", "version": str}`
  - `POST /admin/seed` → the result of `seed_database`
  - `/uploads/*` static mount

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p backend/app/api backend/tests/api
touch backend/app/api/__init__.py backend/tests/api/__init__.py
```

`backend/tests/api/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_a_version():
    assert client.get("/health").json()["version"]


def test_uploads_are_mounted():
    """A missing file must 404 from the static mount, not 500 or route-miss."""
    assert client.get("/uploads/definitely-not-here.jpg").status_code == 404
```

`backend/tests/test_import_rules.py`:

```python
"""Architectural boundary tests.

The AI package must be runnable from a script or a test with no web server, so
it may never import the API layer.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_ai_never_imports_api():
    offenders = []
    for path in (APP / "ai").rglob("*.py"):
        if any(name.startswith("app.api") for name in _imports_in(path)):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, f"app/ai must not import app/api: {offenders}"


def test_api_never_imports_the_graph_directly():
    """The API talks to the graph only through app.ai.graph.runner (Phase 1)."""
    offenders = []
    for path in (APP / "api").rglob("*.py"):
        for name in _imports_in(path):
            if name.startswith("app.ai.graph") and not name.startswith("app.ai.graph.runner"):
                offenders.append(f"{path.relative_to(APP)} -> {name}")
    assert not offenders, f"api must go through the runner: {offenders}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/api tests/test_import_rules.py -v`
Expected: `test_health.py` FAILs with `ModuleNotFoundError: No module named 'app.main'`. The import-rule tests PASS vacuously (`app/ai` and `app/api` are empty or absent) — that is fine; they are guards for Phase 1.

- [ ] **Step 3: Implement the system router**

`backend/app/api/system.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.seed import seed_database

router = APIRouter(tags=["system"])

VERSION = "2.0.0-phase0"


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": VERSION}


@router.post("/admin/seed")
async def seed(db: Session = Depends(get_db)) -> dict:
    return seed_database(db)
```

- [ ] **Step 4: Implement the application**

`backend/app/main.py`:

```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import system

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="CivicAI",
    description="AI-driven government infrastructure complaint resolution",
    version=system.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
```

Note: schema creation is **not** done at startup. Migrations are the only way tables are created, so a schema drift shows up as a migration failure rather than being silently papered over. v1 called `create_tables()` in its lifespan and therefore never exercised its migrations.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/api tests/test_import_rules.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Verify the app actually boots**

```bash
cd backend
DATABASE_URL="sqlite:///./civicai.db" python -m alembic upgrade head
python -m uvicorn app.main:app --port 8000 &
UVICORN_PID=$!
sleep 3
curl -s localhost:8000/health; echo
curl -s -X POST localhost:8000/admin/seed; echo
kill "$UVICORN_PID"
```

`kill %1` is not used here: job control is disabled in non-interactive shells, so it
would fail and leave the server running.

Expected: `{"status":"ok","version":"2.0.0-phase0"}` then `{"message":"Database seeded successfully","tenant_id":"..."}`.

- [ ] **Step 7: Run the full suite and commit**

Run: `cd backend && python -m pytest -v`
Expected: PASS, 39 tests (config 5, baseline 5, core models 6, complaint models 7, AI models 5, seed 5, migration 1, health 3, import rules 2).

```bash
cd /home/martin/Projects/CivicAi
git add backend/app backend/tests
git commit -m "feat: FastAPI application boot with health and seed endpoints

Tables are created only by migrations, never at startup — v1 called
create_tables() in its lifespan and so never exercised its own migrations.

Adds architectural boundary tests enforcing that app/ai never imports app/api
and that app/api reaches the graph only through the runner."
```

---

## Phase 0 Done When

- [ ] `cd backend && python -m pytest` passes with 39 tests and no network access
- [ ] `python -m alembic upgrade head` creates all 17 tables from scratch
- [ ] `uvicorn app.main:app` boots; `GET /health` returns `{"status": "ok", ...}`
- [ ] `POST /admin/seed` populates a tenant, admin, 10 departments and 9 contractors, and is idempotent
- [ ] No LangChain, LangGraph or LLM dependency appears in `requirements.txt`
- [ ] `backend/app/` contains no v1 code except `app/evals/baseline.py`

**Next:** Phase 1 (graph core) gets its own plan, written once Phase 0 is complete.
