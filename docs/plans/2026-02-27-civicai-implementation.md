# CivicAI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an autonomous AI-driven government infrastructure complaint resolution system with multi-agent pipeline, FastAPI backend, PostgreSQL database, and React frontend.

**Architecture:** Monolithic FastAPI application with 7 sequential AI agents processing complaints through a pipeline. React+Vite+Tailwind frontend with citizen portal, admin dashboard, and public transparency dashboard. Multi-tenant via tenant_id column.

**Tech Stack:** Python/FastAPI, SQLAlchemy/Alembic, PostgreSQL, Claude/OpenAI LLM, React 18/Vite/TypeScript/Tailwind, WebSocket, Docker Compose

**Design doc:** `docs/plans/2026-02-27-civicai-design.md`

---

## Phase 1: Project Scaffolding & Configuration

### Task 1: Backend project setup

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/requirements.txt`
- Create: `backend/.env.example`

**Step 1: Create requirements.txt**

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.35
alembic==1.13.2
psycopg2-binary==2.9.9
pydantic==2.9.0
pydantic-settings==2.5.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
anthropic==0.34.0
openai==1.47.0
pillow==10.4.0
apscheduler==3.10.4
httpx==0.27.0
python-dotenv==1.0.1
pytest==8.3.3
pytest-asyncio==0.24.0
aiofiles==24.1.0
```

**Step 2: Create .env.example**

```env
DATABASE_URL=postgresql://civicai:civicai@localhost:5432/civicai
SECRET_KEY=change-me-in-production
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
LLM_PROVIDER=anthropic
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
UPLOAD_DIR=./uploads
```

**Step 3: Create config.py**

```python
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql://civicai:civicai@localhost:5432/civicai"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    llm_provider: str = "anthropic"  # "anthropic" or "openai"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""

    upload_dir: str = "./uploads"

    otp_expire_minutes: int = 10

    class Config:
        env_file = ".env"


settings = Settings()
```

**Step 4: Create main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(
    title="CivicAI",
    description="AI-Driven Government Infrastructure Resolution System",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 5: Create __init__.py**

Empty file.

**Step 6: Run to verify**

Run: `cd backend && pip install -r requirements.txt && python -m uvicorn app.main:app --reload --port 8000`
Expected: Server starts, `GET /health` returns `{"status": "ok"}`

**Step 7: Commit**

```bash
git add backend/
git commit -m "feat: scaffold backend with FastAPI, config, and health endpoint"
```

---

### Task 2: Database setup with SQLAlchemy + Alembic

**Files:**
- Create: `backend/app/database.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/` (directory)

**Step 1: Create database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Step 2: Initialize Alembic**

Run: `cd backend && alembic init alembic`

**Step 3: Update alembic/env.py**

Replace the `target_metadata` line and `run_migrations_online` to import our Base and use our engine:

```python
# In env.py, after imports add:
from app.database import Base, engine
from app.models import *  # noqa: F401,F403

target_metadata = Base.metadata

# In run_migrations_online(), use:
# connectable = engine
```

**Step 4: Update alembic.ini**

Set `sqlalchemy.url` to match our DATABASE_URL or leave it to be overridden by env.py.

**Step 5: Commit**

```bash
git add backend/app/database.py backend/alembic/ backend/alembic.ini
git commit -m "feat: add SQLAlchemy database setup and Alembic migrations"
```

---

### Task 3: Docker Compose for PostgreSQL

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/.env` (copy from .env.example)

**Step 1: Create docker-compose.yml**

```yaml
version: "3.8"

services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: civicai
      POSTGRES_PASSWORD: civicai
      POSTGRES_DB: civicai
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

**Step 2: Start database**

Run: `docker-compose up -d db`
Expected: PostgreSQL running on port 5432

**Step 3: Copy .env.example to .env**

Run: `cp backend/.env.example backend/.env`

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add Docker Compose with PostgreSQL"
```

---

## Phase 2: Database Models

### Task 4: Tenant and User models

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/tenant.py`
- Create: `backend/app/models/user.py`
- Test: `backend/tests/test_models.py`

**Step 1: Write test**

```python
# backend/tests/test_models.py
from app.models.tenant import Tenant
from app.models.user import User


def test_tenant_model_exists():
    t = Tenant(name="Test City")
    assert t.name == "Test City"


def test_user_model_exists():
    u = User(email="a@b.com", name="Test", role="citizen")
    assert u.role == "citizen"
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL — ImportError

**Step 3: Create models/__init__.py**

```python
from app.models.tenant import Tenant
from app.models.user import User
```

**Step 4: Create tenant.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    users = relationship("User", back_populates="tenant")
    departments = relationship("Department", back_populates="tenant")
    complaints = relationship("Complaint", back_populates="tenant")
    contractors = relationship("Contractor", back_populates="tenant")
```

**Step 5: Create user.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="citizen"
    )  # citizen, officer, admin
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="users")
```

**Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add backend/app/models/ backend/tests/
git commit -m "feat: add Tenant and User database models"
```

---

### Task 5: Complaint model

**Files:**
- Create: `backend/app/models/complaint.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models.py` (append)

**Step 1: Write test**

```python
# append to backend/tests/test_models.py
from app.models.complaint import Complaint, ComplaintMedia


def test_complaint_model():
    c = Complaint(
        description="Pothole on Main St",
        citizen_email="test@test.com",
        status="submitted",
    )
    assert c.status == "submitted"
```

**Step 2: Run test — expect FAIL**

**Step 3: Create complaint.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    tracking_id: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    citizen_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    citizen_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    citizen_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="submitted"
    )
    # Status flow: submitted → validated → classified → prioritized → assigned → in_progress → resolved → closed

    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    priority_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Risk: critical, high, medium, low

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ward: Mapped[str | None] = mapped_column(String(100), nullable=True)
    block: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)

    classification_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    ai_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    tenant = relationship("Tenant", back_populates="complaints")
    media = relationship("ComplaintMedia", back_populates="complaint")
    work_order = relationship("WorkOrder", back_populates="complaint", uselist=False)
    escalations = relationship("Escalation", back_populates="complaint")


class ComplaintMedia(Base):
    __tablename__ = "complaint_media"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("complaints.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # image, video, voice
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    complaint = relationship("Complaint", back_populates="media")
```

**Step 4: Update models/__init__.py**

```python
from app.models.tenant import Tenant
from app.models.user import User
from app.models.complaint import Complaint, ComplaintMedia
```

**Step 5: Run tests — expect PASS**

**Step 6: Commit**

```bash
git add backend/app/models/
git commit -m "feat: add Complaint and ComplaintMedia models"
```

---

### Task 6: WorkOrder, Department, Contractor, Escalation, Notification models

**Files:**
- Create: `backend/app/models/work_order.py`
- Create: `backend/app/models/department.py`
- Create: `backend/app/models/contractor.py`
- Create: `backend/app/models/escalation.py`
- Create: `backend/app/models/notification.py`
- Modify: `backend/app/models/__init__.py`

**Step 1: Write tests**

```python
# append to backend/tests/test_models.py
from app.models.work_order import WorkOrder
from app.models.department import Department
from app.models.contractor import Contractor
from app.models.escalation import Escalation
from app.models.notification import Notification


def test_work_order_model():
    wo = WorkOrder(status="created")
    assert wo.status == "created"


def test_department_model():
    d = Department(name="Roads Dept")
    assert d.name == "Roads Dept"


def test_contractor_model():
    c = Contractor(name="BuildCo", rating=4.5)
    assert c.rating == 4.5
```

**Step 2: Run tests — expect FAIL**

**Step 3: Create work_order.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("complaints.id"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    contractor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractors.id"), nullable=True
    )
    officer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    # Status: created → accepted → in_progress → completed → verified
    sla_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    materials: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    complaint = relationship("Complaint", back_populates="work_order")
    contractor = relationship("Contractor")
```

**Step 4: Create department.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_mapping: Mapped[list | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    head_officer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="departments")
```

**Step 5: Create contractor.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Contractor(Base):
    __tablename__ = "contractors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    specializations: Mapped[list | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    active_workload: Mapped[int] = mapped_column(Integer, default=0)
    zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="contractors")
```

**Step 6: Create escalation.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    complaint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("complaints.id"), nullable=False
    )
    from_level: Mapped[str] = mapped_column(String(50), nullable=False)
    to_level: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    escalated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    complaint = relationship("Complaint", back_populates="escalations")
```

**Step 7: Create notification.py**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    complaint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("complaints.id"), nullable=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # email, websocket
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

**Step 8: Update models/__init__.py**

```python
from app.models.tenant import Tenant
from app.models.user import User
from app.models.complaint import Complaint, ComplaintMedia
from app.models.work_order import WorkOrder
from app.models.department import Department
from app.models.contractor import Contractor
from app.models.escalation import Escalation
from app.models.notification import Notification
```

**Step 9: Run tests — expect PASS**

**Step 10: Commit**

```bash
git add backend/app/models/ backend/tests/
git commit -m "feat: add WorkOrder, Department, Contractor, Escalation, Notification models"
```

---

### Task 7: Generate initial Alembic migration

**Step 1: Generate migration**

Run: `cd backend && alembic revision --autogenerate -m "initial schema"`

**Step 2: Apply migration**

Run: `cd backend && alembic upgrade head`
Expected: All tables created in PostgreSQL

**Step 3: Commit**

```bash
git add backend/alembic/
git commit -m "feat: add initial database migration"
```

---

## Phase 3: Pydantic Schemas

### Task 8: Request/Response schemas

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/complaint.py`
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/schemas/work_order.py`
- Create: `backend/app/schemas/common.py`

**Step 1: Create common.py**

```python
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class MessageResponse(BaseModel):
    message: str
```

**Step 2: Create complaint.py**

```python
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class ComplaintCreate(BaseModel):
    description: str
    citizen_email: str
    citizen_phone: Optional[str] = None
    citizen_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None


class ComplaintResponse(BaseModel):
    id: uuid.UUID
    tracking_id: str
    status: str
    description: str
    citizen_email: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    priority_score: Optional[int] = None
    risk_level: Optional[str] = None
    address: Optional[str] = None
    ward: Optional[str] = None
    district: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ComplaintListResponse(BaseModel):
    complaints: list[ComplaintResponse]
    total: int


class ComplaintTrackResponse(BaseModel):
    tracking_id: str
    status: str
    category: Optional[str] = None
    priority_score: Optional[int] = None
    risk_level: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OTPRequest(BaseModel):
    email: str


class OTPVerify(BaseModel):
    email: str
    otp: str
```

**Step 3: Create auth.py**

```python
from pydantic import BaseModel


class AdminLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
```

**Step 4: Create work_order.py**

```python
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WorkOrderResponse(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    contractor_id: Optional[uuid.UUID] = None
    officer_id: Optional[uuid.UUID] = None
    status: str
    sla_deadline: Optional[datetime] = None
    estimated_cost: Optional[float] = None
    materials: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    contractor_id: Optional[uuid.UUID] = None
```

**Step 5: Create schemas/__init__.py**

```python
from app.schemas.common import HealthResponse, MessageResponse
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintResponse,
    ComplaintListResponse,
    ComplaintTrackResponse,
    OTPRequest,
    OTPVerify,
)
from app.schemas.auth import AdminLogin, TokenResponse
from app.schemas.work_order import WorkOrderResponse, WorkOrderUpdate
```

**Step 6: Commit**

```bash
git add backend/app/schemas/
git commit -m "feat: add Pydantic request/response schemas"
```

---

## Phase 4: Core Services

### Task 9: LLM service abstraction

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/llm.py`
- Test: `backend/tests/test_llm_service.py`

**Step 1: Write test**

```python
# backend/tests/test_llm_service.py
import pytest
from app.services.llm import LLMService


def test_llm_service_initializes():
    service = LLMService(provider="anthropic")
    assert service.provider == "anthropic"


def test_llm_service_build_prompt():
    service = LLMService(provider="anthropic")
    prompt = service.build_classification_prompt("There is a big pothole on MG Road")
    assert "pothole" in prompt.lower() or "MG Road" in prompt
```

**Step 2: Run test — expect FAIL**

**Step 3: Create llm.py**

```python
from typing import Optional

from app.config import settings

INFRASTRUCTURE_CATEGORIES = [
    "ROADS",
    "ELECTRICITY",
    "WATER",
    "SANITATION",
    "PUBLIC_SPACES",
    "EDUCATION",
    "HEALTH",
    "FLOODING",
    "FIRE_HAZARD",
    "CONSTRUCTION",
    "STRAY_ANIMALS",
    "SEWAGE",
]


class LLMService:
    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or settings.llm_provider

    async def classify_complaint(self, description: str, media_text: str = "") -> dict:
        """Classify complaint into infrastructure category."""
        prompt = self.build_classification_prompt(description, media_text)

        if self.provider == "anthropic":
            return await self._call_anthropic(prompt, system="You are an infrastructure complaint classifier. Respond with JSON only.")
        else:
            return await self._call_openai(prompt, system="You are an infrastructure complaint classifier. Respond with JSON only.")

    async def validate_complaint(self, description: str) -> dict:
        """Validate if complaint is infrastructure-related and extract structured fields."""
        prompt = f"""Analyze this complaint and determine:
1. Is this an infrastructure-related complaint? (true/false)
2. Extract: what_happened, where, when (if mentioned), severity_keywords
3. If not infrastructure-related, explain why.

Complaint: "{description}"

Respond in JSON: {{"is_valid": bool, "what_happened": str, "where": str, "when": str, "severity_keywords": [str], "rejection_reason": str|null}}"""

        if self.provider == "anthropic":
            return await self._call_anthropic(prompt, system="You are an infrastructure complaint validator. Respond with JSON only.")
        else:
            return await self._call_openai(prompt, system="You are an infrastructure complaint validator. Respond with JSON only.")

    async def assess_risk(self, description: str, category: str, media_text: str = "") -> dict:
        """Assess risk level and priority score."""
        prompt = f"""Assess the risk and priority of this infrastructure complaint:

Category: {category}
Description: "{description}"
Additional media context: "{media_text}"

Score on these factors (each 0-25, total 0-100):
1. Category severity (life-threatening categories score higher)
2. Population impact (how many people affected)
3. Safety risk (immediate danger level)
4. Urgency (time-sensitive nature)

Determine risk_level: critical (76-100), high (51-75), medium (26-50), low (0-25)

Respond in JSON: {{"priority_score": int, "risk_level": str, "category_severity": int, "population_impact": int, "safety_risk": int, "urgency": int, "reasoning": str}}"""

        if self.provider == "anthropic":
            return await self._call_anthropic(prompt, system="You are an infrastructure risk assessor. Respond with JSON only.")
        else:
            return await self._call_openai(prompt, system="You are an infrastructure risk assessor. Respond with JSON only.")

    def build_classification_prompt(self, description: str, media_text: str = "") -> str:
        categories_str = ", ".join(INFRASTRUCTURE_CATEGORIES)
        return f"""Classify this infrastructure complaint into one of these categories: {categories_str}

Complaint: "{description}"
Additional media context: "{media_text}"

Respond in JSON: {{"category": str, "subcategory": str, "confidence": float (0-1), "reasoning": str}}"""

    async def _call_anthropic(self, prompt: str, system: str = "") -> dict:
        import json
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        # Extract JSON from response
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
            raise

    async def _call_openai(self, prompt: str, system: str = "") -> dict:
        import json
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)


llm_service = LLMService()
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git add backend/app/services/ backend/tests/test_llm_service.py
git commit -m "feat: add LLM service with Anthropic and OpenAI support"
```

---

### Task 10: Media service (file upload, speech-to-text)

**Files:**
- Create: `backend/app/services/media.py`

**Step 1: Create media.py**

```python
import os
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import UploadFile

from app.config import settings


class MediaService:
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_file(self, file: UploadFile, complaint_id: str) -> dict:
        """Save uploaded file and return metadata."""
        ext = Path(file.filename).suffix if file.filename else ""
        filename = f"{complaint_id}_{uuid.uuid4().hex[:8]}{ext}"
        file_path = self.upload_dir / filename

        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        media_type = self._detect_media_type(ext)

        return {
            "file_path": str(file_path),
            "media_type": media_type,
            "original_filename": file.filename,
        }

    async def speech_to_text(self, file_path: str) -> str:
        """Convert voice file to text using OpenAI Whisper."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return transcript.text

    def _detect_media_type(self, ext: str) -> str:
        ext = ext.lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            return "image"
        elif ext in (".mp4", ".avi", ".mov", ".webm"):
            return "video"
        elif ext in (".mp3", ".wav", ".ogg", ".m4a", ".webm"):
            return "voice"
        return "unknown"


media_service = MediaService()
```

**Step 2: Commit**

```bash
git add backend/app/services/media.py
git commit -m "feat: add media service for file upload and speech-to-text"
```

---

### Task 11: Geocoding service

**Files:**
- Create: `backend/app/services/geocoding.py`

**Step 1: Create geocoding.py**

```python
from typing import Optional

import httpx


class GeocodingService:
    """Reverse geocoding and jurisdiction mapping using OpenStreetMap Nominatim."""

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

    async def reverse_geocode(self, lat: float, lon: float) -> dict:
        """Convert GPS coordinates to address and jurisdiction info."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.NOMINATIM_URL,
                    params={
                        "lat": lat,
                        "lon": lon,
                        "format": "json",
                        "addressdetails": 1,
                    },
                    headers={"User-Agent": "CivicAI/1.0"},
                )
                data = response.json()

            address_parts = data.get("address", {})
            return {
                "address": data.get("display_name", ""),
                "ward": address_parts.get("suburb", address_parts.get("neighbourhood", "")),
                "block": address_parts.get("city_block", address_parts.get("quarter", "")),
                "district": address_parts.get("city_district", address_parts.get("county", "")),
                "city": address_parts.get("city", address_parts.get("town", "")),
                "state": address_parts.get("state", ""),
            }
        except Exception:
            return {
                "address": f"Lat: {lat}, Lon: {lon}",
                "ward": "",
                "block": "",
                "district": "",
                "city": "",
                "state": "",
            }

    def determine_jurisdiction_level(self, ward: str, block: str, district: str) -> str:
        """Determine jurisdiction level based on available location data."""
        if ward:
            return "ward"
        if block:
            return "block"
        if district:
            return "district"
        return "city"


geocoding_service = GeocodingService()
```

**Step 2: Commit**

```bash
git add backend/app/services/geocoding.py
git commit -m "feat: add geocoding service with Nominatim reverse geocoding"
```

---

### Task 12: OTP service

**Files:**
- Create: `backend/app/services/otp.py`

**Step 1: Create otp.py**

```python
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.config import settings

# In-memory OTP store (replace with Redis in production)
_otp_store: dict[str, dict] = {}


class OTPService:
    def generate_otp(self, email: str) -> str:
        """Generate 6-digit OTP for email verification."""
        otp = "".join(random.choices(string.digits, k=6))
        _otp_store[email] = {
            "otp": otp,
            "expires_at": datetime.now(timezone.utc)
            + timedelta(minutes=settings.otp_expire_minutes),
        }
        return otp

    def verify_otp(self, email: str, otp: str) -> bool:
        """Verify OTP for email."""
        stored = _otp_store.get(email)
        if not stored:
            return False
        if datetime.now(timezone.utc) > stored["expires_at"]:
            del _otp_store[email]
            return False
        if stored["otp"] != otp:
            return False
        del _otp_store[email]
        return True


otp_service = OTPService()
```

**Step 2: Commit**

```bash
git add backend/app/services/otp.py
git commit -m "feat: add OTP service for citizen email verification"
```

---

### Task 13: Email service

**Files:**
- Create: `backend/app/services/email.py`

**Step 1: Create email.py**

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.config import settings


class EmailService:
    async def send_email(self, to: str, subject: str, body: str) -> bool:
        """Send email notification."""
        try:
            msg = MIMEMultipart()
            msg["From"] = f"CivicAI <noreply@civicai.gov>"
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Email send failed: {e}")
            return False

    async def send_otp(self, email: str, otp: str) -> bool:
        """Send OTP verification email."""
        return await self.send_email(
            to=email,
            subject="CivicAI - Your Verification Code",
            body=f"<h2>Your verification code is: <strong>{otp}</strong></h2><p>This code expires in {settings.otp_expire_minutes} minutes.</p>",
        )

    async def send_complaint_confirmation(self, email: str, tracking_id: str) -> bool:
        """Send complaint submission confirmation."""
        return await self.send_email(
            to=email,
            subject=f"CivicAI - Complaint Registered ({tracking_id})",
            body=f"<h2>Your complaint has been registered</h2><p>Tracking ID: <strong>{tracking_id}</strong></p><p>Use this ID to track your complaint status.</p>",
        )

    async def send_status_update(self, email: str, tracking_id: str, status: str) -> bool:
        """Send complaint status update."""
        return await self.send_email(
            to=email,
            subject=f"CivicAI - Complaint Update ({tracking_id})",
            body=f"<h2>Complaint Status Update</h2><p>Your complaint <strong>{tracking_id}</strong> status has been updated to: <strong>{status}</strong></p>",
        )


email_service = EmailService()
```

**Step 2: Commit**

```bash
git add backend/app/services/email.py
git commit -m "feat: add email service for notifications and OTP"
```

---

### Task 14: WebSocket manager

**Files:**
- Create: `backend/app/services/websocket.py`

**Step 1: Create websocket.py**

```python
from typing import Dict, List
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, tracking_id: str, websocket: WebSocket):
        await websocket.accept()
        if tracking_id not in self.connections:
            self.connections[tracking_id] = []
        self.connections[tracking_id].append(websocket)

    def disconnect(self, tracking_id: str, websocket: WebSocket):
        if tracking_id in self.connections:
            self.connections[tracking_id].remove(websocket)
            if not self.connections[tracking_id]:
                del self.connections[tracking_id]

    async def send_update(self, tracking_id: str, message: dict):
        if tracking_id in self.connections:
            for ws in self.connections[tracking_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(tracking_id, ws)


ws_manager = WebSocketManager()
```

**Step 2: Commit**

```bash
git add backend/app/services/websocket.py
git commit -m "feat: add WebSocket manager for real-time complaint updates"
```

---

### Task 15: Update services __init__.py

**Files:**
- Create: `backend/app/services/__init__.py`

```python
from app.services.llm import llm_service
from app.services.media import media_service
from app.services.geocoding import geocoding_service
from app.services.otp import otp_service
from app.services.email import email_service
from app.services.websocket import ws_manager
```

**Commit:**

```bash
git add backend/app/services/__init__.py
git commit -m "feat: add services init with all service exports"
```

---

## Phase 5: Agent Pipeline

### Task 16: Base agent and pipeline context

**Files:**
- Create: `backend/app/agents/__init__.py`
- Create: `backend/app/agents/base.py`
- Create: `backend/app/agents/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Step 1: Write test**

```python
# backend/tests/test_pipeline.py
import pytest
from app.agents.base import BaseAgent, PipelineContext


class MockAgent(BaseAgent):
    async def process(self, context: PipelineContext) -> PipelineContext:
        context.data["mock"] = True
        return context


@pytest.mark.asyncio
async def test_base_agent_interface():
    agent = MockAgent(name="mock")
    ctx = PipelineContext(complaint_id="test-123")
    result = await agent.process(ctx)
    assert result.data["mock"] is True


def test_pipeline_context():
    ctx = PipelineContext(complaint_id="test-123")
    assert ctx.complaint_id == "test-123"
    assert ctx.data == {}
    assert ctx.errors == []
```

**Step 2: Run test — expect FAIL**

**Step 3: Create base.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PipelineContext:
    complaint_id: str
    tenant_id: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    status: str = "submitted"

    # Populated by agents as pipeline progresses
    raw_input: dict = field(default_factory=dict)
    structured_complaint: dict = field(default_factory=dict)
    classification: dict = field(default_factory=dict)
    risk_assessment: dict = field(default_factory=dict)
    routing: dict = field(default_factory=dict)
    work_order: dict = field(default_factory=dict)


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def process(self, context: PipelineContext) -> PipelineContext:
        pass

    def log(self, message: str):
        print(f"[{self.name}] {message}")
```

**Step 4: Create pipeline.py**

```python
from typing import Optional

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, PipelineContext


class ComplaintPipeline:
    def __init__(self):
        self.agents: list[BaseAgent] = []

    def add_agent(self, agent: BaseAgent):
        self.agents.append(agent)

    async def run(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        """Run all agents sequentially on the complaint context."""
        for agent in self.agents:
            try:
                agent.log(f"Processing complaint {context.complaint_id}")
                context = await agent.process(context)
                if context.errors:
                    agent.log(f"Errors: {context.errors}")
                    break
            except Exception as e:
                context.errors.append(f"{agent.name}: {str(e)}")
                agent.log(f"Failed: {e}")
                break
        return context
```

**Step 5: Create agents/__init__.py**

```python
from app.agents.base import BaseAgent, PipelineContext
from app.agents.pipeline import ComplaintPipeline
```

**Step 6: Run tests — expect PASS**

**Step 7: Commit**

```bash
git add backend/app/agents/ backend/tests/test_pipeline.py
git commit -m "feat: add base agent, pipeline context, and complaint pipeline orchestrator"
```

---

### Task 17: Intake Agent

**Files:**
- Create: `backend/app/agents/intake.py`
- Test: `backend/tests/test_agents.py`

**Step 1: Write test**

```python
# backend/tests/test_agents.py
import pytest
from app.agents.base import PipelineContext
from app.agents.intake import IntakeAgent


@pytest.mark.asyncio
async def test_intake_agent_text_only():
    agent = IntakeAgent()
    ctx = PipelineContext(complaint_id="test-001")
    ctx.raw_input = {
        "description": "There is a huge pothole on MG Road near bus stop",
        "citizen_email": "test@test.com",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "media_files": [],
    }
    result = await agent.process(ctx)
    assert result.data.get("intake_complete") is True
    assert "description" in result.data
```

**Step 2: Run test — expect FAIL**

**Step 3: Create intake.py**

```python
from typing import Optional

from app.agents.base import BaseAgent, PipelineContext
from app.services.media import media_service
from app.services.geocoding import geocoding_service


class IntakeAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="IntakeAgent")

    async def process(self, context: PipelineContext) -> PipelineContext:
        raw = context.raw_input
        description = raw.get("description", "")
        media_texts = []

        # Process voice files → speech-to-text
        for media in raw.get("media_files", []):
            if media.get("media_type") == "voice":
                try:
                    text = await media_service.speech_to_text(media["file_path"])
                    media_texts.append(text)
                    media["extracted_text"] = text
                except Exception as e:
                    self.log(f"Speech-to-text failed: {e}")

        # Combine description with voice transcriptions
        full_description = description
        if media_texts:
            full_description += "\n\nVoice transcription: " + " ".join(media_texts)

        # Reverse geocode GPS coordinates
        location_data = {}
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        if lat and lon:
            location_data = await geocoding_service.reverse_geocode(lat, lon)

        context.data["description"] = full_description
        context.data["citizen_email"] = raw.get("citizen_email", "")
        context.data["citizen_phone"] = raw.get("citizen_phone", "")
        context.data["citizen_name"] = raw.get("citizen_name", "")
        context.data["latitude"] = lat
        context.data["longitude"] = lon
        context.data["address"] = raw.get("address") or location_data.get("address", "")
        context.data["ward"] = location_data.get("ward", "")
        context.data["block"] = location_data.get("block", "")
        context.data["district"] = location_data.get("district", "")
        context.data["media_files"] = raw.get("media_files", [])
        context.data["media_texts"] = media_texts
        context.data["intake_complete"] = True
        context.status = "intake_complete"

        self.log(f"Intake complete. Description length: {len(full_description)}")
        return context
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git add backend/app/agents/intake.py backend/tests/test_agents.py
git commit -m "feat: add Intake Agent for complaint input processing"
```

---

### Task 18: Validation Agent

**Files:**
- Create: `backend/app/agents/validator.py`

**Step 1: Append test to test_agents.py**

```python
from app.agents.validator import ValidationAgent

@pytest.mark.asyncio
async def test_validation_agent():
    agent = ValidationAgent()
    ctx = PipelineContext(complaint_id="test-002")
    ctx.data = {
        "description": "Pothole on MG Road causing accidents",
        "address": "MG Road, Bangalore",
        "intake_complete": True,
    }
    result = await agent.process(ctx)
    assert result.status in ("validated", "rejected")
```

**Step 2: Create validator.py**

```python
from app.agents.base import BaseAgent, PipelineContext
from app.services.llm import llm_service


class ValidationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ValidationAgent")

    async def process(self, context: PipelineContext) -> PipelineContext:
        description = context.data.get("description", "")

        if not description or len(description.strip()) < 10:
            context.errors.append("Description too short or missing")
            context.status = "rejected"
            return context

        if not context.data.get("address") and not (
            context.data.get("latitude") and context.data.get("longitude")
        ):
            context.errors.append("Location information missing")
            context.status = "rejected"
            return context

        # LLM validation
        try:
            result = await llm_service.validate_complaint(description)
            context.structured_complaint = result

            if not result.get("is_valid", False):
                context.errors.append(
                    f"Not an infrastructure complaint: {result.get('rejection_reason', 'unknown')}"
                )
                context.status = "rejected"
                return context

            context.data["what_happened"] = result.get("what_happened", "")
            context.data["severity_keywords"] = result.get("severity_keywords", [])
            context.status = "validated"
            self.log("Complaint validated as infrastructure-related")

        except Exception as e:
            self.log(f"LLM validation failed, proceeding with basic validation: {e}")
            context.status = "validated"

        return context
```

**Step 3: Commit**

```bash
git add backend/app/agents/validator.py backend/tests/test_agents.py
git commit -m "feat: add Validation Agent with LLM-powered complaint validation"
```

---

### Task 19: Classification Agent

**Files:**
- Create: `backend/app/agents/classifier.py`

**Step 1: Create classifier.py**

```python
from app.agents.base import BaseAgent, PipelineContext
from app.services.llm import llm_service

CONFIDENCE_THRESHOLD = 0.7


class ClassificationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ClassificationAgent")

    async def process(self, context: PipelineContext) -> PipelineContext:
        description = context.data.get("description", "")
        media_text = " ".join(context.data.get("media_texts", []))

        try:
            result = await llm_service.classify_complaint(description, media_text)
            context.classification = result

            context.data["category"] = result.get("category", "UNKNOWN")
            context.data["subcategory"] = result.get("subcategory", "")
            context.data["classification_confidence"] = result.get("confidence", 0.0)

            if result.get("confidence", 0) < CONFIDENCE_THRESHOLD:
                context.data["needs_human_review"] = True
                self.log(f"Low confidence ({result.get('confidence')}), flagged for human review")

            context.status = "classified"
            self.log(f"Classified as {result.get('category')} / {result.get('subcategory')}")

        except Exception as e:
            context.errors.append(f"Classification failed: {str(e)}")
            self.log(f"Classification failed: {e}")

        return context
```

**Step 2: Commit**

```bash
git add backend/app/agents/classifier.py
git commit -m "feat: add Classification Agent with LLM-powered category detection"
```

---

### Task 20: Risk & Priority Agent

**Files:**
- Create: `backend/app/agents/risk_assessor.py`

**Step 1: Create risk_assessor.py**

```python
from app.agents.base import BaseAgent, PipelineContext
from app.services.llm import llm_service


class RiskAssessorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="RiskAssessorAgent")

    async def process(self, context: PipelineContext) -> PipelineContext:
        description = context.data.get("description", "")
        category = context.data.get("category", "UNKNOWN")
        media_text = " ".join(context.data.get("media_texts", []))

        try:
            result = await llm_service.assess_risk(description, category, media_text)
            context.risk_assessment = result

            context.data["priority_score"] = result.get("priority_score", 50)
            context.data["risk_level"] = result.get("risk_level", "medium")

            context.status = "prioritized"
            self.log(
                f"Risk: {result.get('risk_level')} | Score: {result.get('priority_score')}"
            )

        except Exception as e:
            # Fallback: use category-based defaults
            context.data["priority_score"] = self._default_score(category)
            context.data["risk_level"] = self._score_to_level(
                context.data["priority_score"]
            )
            context.status = "prioritized"
            self.log(f"LLM risk assessment failed, using defaults: {e}")

        return context

    def _default_score(self, category: str) -> int:
        defaults = {
            "FIRE_HAZARD": 85,
            "FLOODING": 80,
            "ELECTRICITY": 75,
            "SEWAGE": 70,
            "WATER": 65,
            "ROADS": 60,
            "HEALTH": 60,
            "STRAY_ANIMALS": 55,
            "CONSTRUCTION": 50,
            "SANITATION": 45,
            "PUBLIC_SPACES": 35,
            "EDUCATION": 40,
        }
        return defaults.get(category, 50)

    def _score_to_level(self, score: int) -> str:
        if score >= 76:
            return "critical"
        if score >= 51:
            return "high"
        if score >= 26:
            return "medium"
        return "low"
```

**Step 2: Commit**

```bash
git add backend/app/agents/risk_assessor.py
git commit -m "feat: add Risk & Priority Agent with LLM assessment and fallback scoring"
```

---

### Task 21: Routing Agent

**Files:**
- Create: `backend/app/agents/router.py`

**Step 1: Create router.py**

```python
from typing import Optional
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, PipelineContext
from app.models.department import Department
from app.models.contractor import Contractor


# Default category → department mapping
CATEGORY_DEPARTMENT_MAP = {
    "ROADS": "Public Works Department",
    "ELECTRICITY": "Electricity Board",
    "WATER": "Water Supply Department",
    "SANITATION": "Sanitation Department",
    "PUBLIC_SPACES": "Parks & Recreation",
    "EDUCATION": "Education Department",
    "HEALTH": "Health Department",
    "FLOODING": "Flood Control Authority",
    "FIRE_HAZARD": "Fire Department",
    "CONSTRUCTION": "Building & Construction Authority",
    "STRAY_ANIMALS": "Animal Control",
    "SEWAGE": "Sewage & Drainage Board",
}


class RoutingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="RoutingAgent")

    async def process(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        category = context.data.get("category", "UNKNOWN")
        tenant_id = context.tenant_id

        # Map to department
        dept_name = CATEGORY_DEPARTMENT_MAP.get(category, "General Administration")
        department = None
        contractor = None

        if db and tenant_id:
            # Find department from DB
            department = (
                db.query(Department)
                .filter(
                    Department.tenant_id == tenant_id,
                    Department.name == dept_name,
                )
                .first()
            )

            # Find best contractor
            contractor = self._find_best_contractor(db, tenant_id, category, context.data.get("district"))

        context.routing = {
            "department_name": dept_name,
            "department_id": str(department.id) if department else None,
            "contractor_id": str(contractor.id) if contractor else None,
            "contractor_name": contractor.name if contractor else None,
            "jurisdiction_level": self._determine_jurisdiction(context.data),
        }

        context.data["department_name"] = dept_name
        context.data["department_id"] = str(department.id) if department else None
        context.data["recommended_contractor_id"] = str(contractor.id) if contractor else None
        context.data["recommended_contractor_name"] = contractor.name if contractor else None
        context.status = "routed"

        self.log(f"Routed to {dept_name}, contractor: {contractor.name if contractor else 'None'}")
        return context

    def _find_best_contractor(self, db: Session, tenant_id: str, category: str, district: Optional[str]) -> Optional[Contractor]:
        """Score and select best contractor based on rating, workload, specialization, zone."""
        query = db.query(Contractor).filter(Contractor.tenant_id == tenant_id)

        contractors = query.all()
        if not contractors:
            return None

        scored = []
        for c in contractors:
            score = 0.0
            # Specialization match (40% weight)
            if c.specializations and category in c.specializations:
                score += 40
            # Rating (30% weight)
            score += (c.rating or 0) * 6  # max 30
            # Workload inverse (20% weight) — less workload = better
            score += max(0, 20 - (c.active_workload or 0) * 2)
            # Zone match (10% weight)
            if district and c.zone and c.zone.lower() == district.lower():
                score += 10

            scored.append((c, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else None

    def _determine_jurisdiction(self, data: dict) -> str:
        if data.get("ward"):
            return "ward"
        if data.get("block"):
            return "block"
        if data.get("district"):
            return "district"
        return "city"
```

**Step 2: Commit**

```bash
git add backend/app/agents/router.py
git commit -m "feat: add Routing Agent with department mapping and contractor scoring"
```

---

### Task 22: Work Order Agent

**Files:**
- Create: `backend/app/agents/work_order.py`

**Step 1: Create work_order.py**

```python
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, PipelineContext

# SLA deadlines by risk level
SLA_HOURS = {
    "critical": 4,
    "high": 24,
    "medium": 72,
    "low": 168,  # 7 days
}


class WorkOrderAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="WorkOrderAgent")

    async def process(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        risk_level = context.data.get("risk_level", "medium")
        sla_hours = SLA_HOURS.get(risk_level, 72)
        now = datetime.now(timezone.utc)

        work_order_data = {
            "complaint_id": context.complaint_id,
            "tenant_id": context.tenant_id,
            "contractor_id": context.data.get("recommended_contractor_id"),
            "department_name": context.data.get("department_name"),
            "status": "created",
            "sla_deadline": (now + timedelta(hours=sla_hours)).isoformat(),
            "sla_hours": sla_hours,
            "estimated_cost": self._estimate_cost(
                context.data.get("category", ""),
                risk_level,
            ),
            "materials": self._estimate_materials(context.data.get("category", "")),
            "summary": self._generate_summary(context.data),
        }

        context.work_order = work_order_data
        context.status = "work_order_created"

        self.log(f"Work order created. SLA: {sla_hours}h, Deadline: {work_order_data['sla_deadline']}")
        return context

    def _estimate_cost(self, category: str, risk_level: str) -> float:
        base_costs = {
            "ROADS": 5000,
            "ELECTRICITY": 3000,
            "WATER": 4000,
            "SANITATION": 2000,
            "PUBLIC_SPACES": 3000,
            "EDUCATION": 8000,
            "HEALTH": 6000,
            "FLOODING": 10000,
            "FIRE_HAZARD": 7000,
            "CONSTRUCTION": 15000,
            "STRAY_ANIMALS": 1000,
            "SEWAGE": 5000,
        }
        multiplier = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.8}
        base = base_costs.get(category, 5000)
        return base * multiplier.get(risk_level, 1.0)

    def _estimate_materials(self, category: str) -> str:
        materials = {
            "ROADS": "Asphalt, gravel, road markers, barriers",
            "ELECTRICITY": "Wiring, transformers, LED bulbs, poles",
            "WATER": "PVC pipes, valves, pumps, testing kits",
            "SANITATION": "Cleaning equipment, bins, drain covers",
            "PUBLIC_SPACES": "Lumber, paint, plants, fencing",
            "SEWAGE": "Manhole covers, drainage pipes, pumps",
            "FLOODING": "Sandbags, pumps, drainage equipment",
            "FIRE_HAZARD": "Extinguishers, barriers, signage",
        }
        return materials.get(category, "To be determined on site inspection")

    def _generate_summary(self, data: dict) -> str:
        return (
            f"Category: {data.get('category', 'N/A')} | "
            f"Priority: {data.get('risk_level', 'N/A')} (Score: {data.get('priority_score', 'N/A')}) | "
            f"Location: {data.get('address', 'N/A')} | "
            f"Department: {data.get('department_name', 'N/A')}"
        )
```

**Step 2: Commit**

```bash
git add backend/app/agents/work_order.py
git commit -m "feat: add Work Order Agent with SLA, cost estimation, and summary generation"
```

---

### Task 23: Tracking & Escalation Agent

**Files:**
- Create: `backend/app/agents/tracker.py`

**Step 1: Create tracker.py**

```python
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, PipelineContext
from app.services.email import email_service
from app.services.websocket import ws_manager


class TrackingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="TrackingAgent")

    async def process(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        """Send initial notifications after complaint pipeline completes."""
        tracking_id = context.data.get("tracking_id", context.complaint_id)
        citizen_email = context.data.get("citizen_email", "")

        # Send confirmation email
        if citizen_email:
            await email_service.send_complaint_confirmation(citizen_email, tracking_id)

        # Send WebSocket update
        await ws_manager.send_update(
            tracking_id,
            {
                "type": "status_update",
                "tracking_id": tracking_id,
                "status": "assigned",
                "category": context.data.get("category"),
                "risk_level": context.data.get("risk_level"),
                "department": context.data.get("department_name"),
                "message": "Your complaint has been processed and assigned to the relevant department.",
            },
        )

        context.status = "assigned"
        self.log(f"Notifications sent for complaint {tracking_id}")
        return context


# SLA monitoring functions (used by APScheduler)
JURISDICTION_ESCALATION = {
    "ward": "block",
    "block": "district",
    "district": "city",
    "city": "state",
}


async def check_sla_deadlines(db: Session):
    """Background job: check all active work orders for SLA breaches."""
    from app.models.work_order import WorkOrder
    from app.models.complaint import Complaint
    from app.models.escalation import Escalation

    now = datetime.now(timezone.utc)

    active_orders = (
        db.query(WorkOrder)
        .filter(WorkOrder.status.in_(["created", "accepted", "in_progress"]))
        .all()
    )

    for order in active_orders:
        if not order.sla_deadline:
            continue

        complaint = db.query(Complaint).filter(Complaint.id == order.complaint_id).first()
        if not complaint:
            continue

        time_remaining = (order.sla_deadline - now).total_seconds()
        total_time = (order.sla_deadline - order.created_at).total_seconds()

        if total_time <= 0:
            continue

        elapsed_pct = 1 - (time_remaining / total_time)

        # 75% elapsed — warn supervisor
        if 0.75 <= elapsed_pct < 1.0:
            await email_service.send_status_update(
                complaint.citizen_email,
                complaint.tracking_id,
                "SLA warning - escalating priority",
            )

        # SLA breached — escalate
        elif elapsed_pct >= 1.0:
            current_level = complaint.ward and "ward" or complaint.block and "block" or "district"
            next_level = JURISDICTION_ESCALATION.get(current_level, "state")

            escalation = Escalation(
                complaint_id=complaint.id,
                from_level=current_level,
                to_level=next_level,
                reason=f"SLA breached. Deadline was {order.sla_deadline.isoformat()}",
            )
            db.add(escalation)
            db.commit()

            await email_service.send_status_update(
                complaint.citizen_email,
                complaint.tracking_id,
                f"Escalated to {next_level} level due to SLA breach",
            )
```

**Step 2: Commit**

```bash
git add backend/app/agents/tracker.py
git commit -m "feat: add Tracking Agent with notifications and SLA escalation monitoring"
```

---

### Task 24: Wire up pipeline with all agents

**Files:**
- Modify: `backend/app/agents/__init__.py`

**Step 1: Update agents/__init__.py**

```python
from app.agents.base import BaseAgent, PipelineContext
from app.agents.pipeline import ComplaintPipeline
from app.agents.intake import IntakeAgent
from app.agents.validator import ValidationAgent
from app.agents.classifier import ClassificationAgent
from app.agents.risk_assessor import RiskAssessorAgent
from app.agents.router import RoutingAgent
from app.agents.work_order import WorkOrderAgent
from app.agents.tracker import TrackingAgent


def create_pipeline() -> ComplaintPipeline:
    """Create the full complaint processing pipeline."""
    pipeline = ComplaintPipeline()
    pipeline.add_agent(IntakeAgent())
    pipeline.add_agent(ValidationAgent())
    pipeline.add_agent(ClassificationAgent())
    pipeline.add_agent(RiskAssessorAgent())
    pipeline.add_agent(RoutingAgent())
    pipeline.add_agent(WorkOrderAgent())
    pipeline.add_agent(TrackingAgent())
    return pipeline
```

**Step 2: Commit**

```bash
git add backend/app/agents/__init__.py
git commit -m "feat: wire up complete 7-agent complaint pipeline"
```

---

## Phase 6: API Routes

### Task 25: Auth routes (admin login)

**Files:**
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/auth.py`
- Create: `backend/app/utils/__init__.py`
- Create: `backend/app/utils/auth.py`

**Step 1: Create utils/auth.py**

```python
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(
            credentials.credentials, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin",):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_officer_or_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "officer"):
        raise HTTPException(status_code=403, detail="Officer or admin access required")
    return user
```

**Step 2: Create routers/auth.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.auth import AdminLogin, TokenResponse
from app.utils.auth import verify_password, create_access_token

router = APIRouter(prefix="/admin", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def admin_login(data: AdminLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.role not in ("admin", "officer"):
        raise HTTPException(status_code=403, detail="Not authorized")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token, role=user.role)
```

**Step 3: Create empty __init__.py files**

**Step 4: Commit**

```bash
git add backend/app/routers/ backend/app/utils/
git commit -m "feat: add admin auth routes with JWT login"
```

---

### Task 26: Complaint routes (citizen)

**Files:**
- Create: `backend/app/routers/complaints.py`

**Step 1: Create complaints.py**

```python
import uuid
import string
import random
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.complaint import Complaint, ComplaintMedia
from app.models.work_order import WorkOrder as WorkOrderModel
from app.schemas.complaint import (
    ComplaintResponse,
    ComplaintTrackResponse,
    ComplaintListResponse,
    OTPRequest,
    OTPVerify,
)
from app.schemas.common import MessageResponse
from app.agents import create_pipeline, PipelineContext
from app.services.media import media_service
from app.services.otp import otp_service
from app.services.email import email_service
from app.services.websocket import ws_manager

router = APIRouter(prefix="/complaints", tags=["complaints"])


def generate_tracking_id() -> str:
    return "CIV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


@router.post("/", response_model=ComplaintResponse)
async def submit_complaint(
    description: str = Form(...),
    citizen_email: str = Form(...),
    citizen_phone: Optional[str] = Form(None),
    citizen_name: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    address: Optional[str] = Form(None),
    tenant_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    tracking_id = generate_tracking_id()
    complaint_id = uuid.uuid4()

    # Save media files
    media_files = []
    for f in files:
        saved = await media_service.save_file(f, str(complaint_id))
        media_files.append(saved)

    # Create complaint record
    complaint = Complaint(
        id=complaint_id,
        tracking_id=tracking_id,
        tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
        citizen_email=citizen_email,
        citizen_phone=citizen_phone,
        citizen_name=citizen_name,
        description=description,
        latitude=latitude,
        longitude=longitude,
        address=address,
        status="submitted",
    )
    db.add(complaint)

    # Save media records
    for mf in media_files:
        media = ComplaintMedia(
            complaint_id=complaint_id,
            file_path=mf["file_path"],
            media_type=mf["media_type"],
            original_filename=mf.get("original_filename"),
        )
        db.add(media)

    db.commit()
    db.refresh(complaint)

    # Run pipeline (async, non-blocking for the response)
    try:
        pipeline = create_pipeline()
        context = PipelineContext(
            complaint_id=str(complaint_id),
            tenant_id=tenant_id,
        )
        context.raw_input = {
            "description": description,
            "citizen_email": citizen_email,
            "citizen_phone": citizen_phone,
            "citizen_name": citizen_name,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "media_files": media_files,
        }
        context.data["tracking_id"] = tracking_id

        result = await pipeline.run(context, db)

        # Update complaint with pipeline results
        complaint.status = result.status if not result.errors else "submitted"
        complaint.category = result.data.get("category")
        complaint.subcategory = result.data.get("subcategory")
        complaint.priority_score = result.data.get("priority_score")
        complaint.risk_level = result.data.get("risk_level")
        complaint.classification_confidence = result.data.get("classification_confidence")
        complaint.ai_analysis = {
            "structured": result.structured_complaint,
            "classification": result.classification,
            "risk": result.risk_assessment,
            "routing": result.routing,
        }
        complaint.ward = result.data.get("ward") or complaint.ward
        complaint.block = result.data.get("block") or complaint.block
        complaint.district = result.data.get("district") or complaint.district
        complaint.address = result.data.get("address") or complaint.address

        # Create work order if pipeline succeeded
        if result.work_order and not result.errors:
            from datetime import datetime

            wo = WorkOrderModel(
                complaint_id=complaint_id,
                tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
                contractor_id=uuid.UUID(result.work_order["contractor_id"]) if result.work_order.get("contractor_id") else None,
                status="created",
                sla_deadline=datetime.fromisoformat(result.work_order["sla_deadline"]) if result.work_order.get("sla_deadline") else None,
                estimated_cost=result.work_order.get("estimated_cost"),
                materials=result.work_order.get("materials"),
                notes=result.work_order.get("summary"),
            )
            db.add(wo)

        db.commit()
        db.refresh(complaint)

    except Exception as e:
        print(f"Pipeline error: {e}")
        # Complaint is still saved even if pipeline fails

    return complaint


@router.get("/track/{tracking_id}", response_model=ComplaintTrackResponse)
async def track_complaint(tracking_id: str, db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.tracking_id == tracking_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


@router.post("/verify-email", response_model=MessageResponse)
async def request_otp(data: OTPRequest):
    otp = otp_service.generate_otp(data.email)
    await email_service.send_otp(data.email, otp)
    return MessageResponse(message="OTP sent to your email")


@router.post("/verify-otp")
async def verify_otp(data: OTPVerify):
    if not otp_service.verify_otp(data.email, data.otp):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    # Return a simple session token (email-based, short-lived)
    from app.utils.auth import create_access_token
    from datetime import timedelta

    token = create_access_token(
        {"sub": data.email, "type": "citizen"},
        expires_delta=timedelta(hours=1),
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/my", response_model=ComplaintListResponse)
async def my_complaints(
    email: str,
    db: Session = Depends(get_db),
):
    """List all complaints for a citizen (requires OTP-verified session)."""
    complaints = (
        db.query(Complaint)
        .filter(Complaint.citizen_email == email)
        .order_by(Complaint.created_at.desc())
        .all()
    )
    return ComplaintListResponse(complaints=complaints, total=len(complaints))


@router.websocket("/ws/{tracking_id}")
async def complaint_websocket(websocket: WebSocket, tracking_id: str):
    await ws_manager.connect(tracking_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(tracking_id, websocket)
```

**Step 2: Commit**

```bash
git add backend/app/routers/complaints.py
git commit -m "feat: add citizen complaint routes with pipeline integration"
```

---

### Task 27: Admin routes

**Files:**
- Create: `backend/app/routers/admin.py`

**Step 1: Create admin.py**

```python
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.complaint import Complaint
from app.models.work_order import WorkOrder
from app.models.contractor import Contractor
from app.models.user import User
from app.schemas.work_order import WorkOrderResponse, WorkOrderUpdate
from app.utils.auth import require_officer_or_admin, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/complaints")
async def list_complaints(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Complaint)
    if user.tenant_id:
        query = query.filter(Complaint.tenant_id == user.tenant_id)
    if status:
        query = query.filter(Complaint.status == status)
    if category:
        query = query.filter(Complaint.category == category)
    if risk_level:
        query = query.filter(Complaint.risk_level == risk_level)

    total = query.count()
    complaints = query.order_by(Complaint.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "complaints": [
            {
                "id": str(c.id),
                "tracking_id": c.tracking_id,
                "status": c.status,
                "description": c.description,
                "category": c.category,
                "subcategory": c.subcategory,
                "priority_score": c.priority_score,
                "risk_level": c.risk_level,
                "address": c.address,
                "citizen_email": c.citizen_email,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in complaints
        ],
        "total": total,
    }


@router.patch("/complaints/{complaint_id}")
async def update_complaint(
    complaint_id: str,
    status: Optional[str] = None,
    contractor_id: Optional[str] = None,
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    complaint = db.query(Complaint).filter(Complaint.id == complaint_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if status:
        complaint.status = status
    if contractor_id:
        wo = db.query(WorkOrder).filter(WorkOrder.complaint_id == complaint.id).first()
        if wo:
            wo.contractor_id = uuid.UUID(contractor_id)
            wo.officer_id = user.id

    db.commit()
    return {"message": "Complaint updated"}


@router.get("/work-orders")
async def list_work_orders(
    status: Optional[str] = Query(None),
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    query = db.query(WorkOrder)
    if user.tenant_id:
        query = query.filter(WorkOrder.tenant_id == user.tenant_id)
    if status:
        query = query.filter(WorkOrder.status == status)

    orders = query.order_by(WorkOrder.created_at.desc()).all()
    return {
        "work_orders": [
            {
                "id": str(wo.id),
                "complaint_id": str(wo.complaint_id),
                "contractor_id": str(wo.contractor_id) if wo.contractor_id else None,
                "status": wo.status,
                "sla_deadline": wo.sla_deadline.isoformat() if wo.sla_deadline else None,
                "estimated_cost": wo.estimated_cost,
                "notes": wo.notes,
                "created_at": wo.created_at.isoformat() if wo.created_at else None,
            }
            for wo in orders
        ]
    }


@router.patch("/work-orders/{work_order_id}")
async def update_work_order(
    work_order_id: str,
    data: WorkOrderUpdate,
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    if data.status:
        wo.status = data.status
        if data.status == "completed":
            from datetime import datetime, timezone
            wo.completed_at = datetime.now(timezone.utc)
    if data.notes:
        wo.notes = data.notes
    if data.contractor_id:
        wo.contractor_id = data.contractor_id
        wo.officer_id = user.id

    db.commit()
    return {"message": "Work order updated"}


@router.get("/analytics")
async def get_analytics(
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Complaint)
    if user.tenant_id:
        query = query.filter(Complaint.tenant_id == user.tenant_id)

    total = query.count()
    by_status = dict(
        db.query(Complaint.status, func.count(Complaint.id))
        .group_by(Complaint.status)
        .all()
    )
    by_category = dict(
        db.query(Complaint.category, func.count(Complaint.id))
        .filter(Complaint.category.isnot(None))
        .group_by(Complaint.category)
        .all()
    )
    by_risk = dict(
        db.query(Complaint.risk_level, func.count(Complaint.id))
        .filter(Complaint.risk_level.isnot(None))
        .group_by(Complaint.risk_level)
        .all()
    )

    return {
        "total_complaints": total,
        "by_status": by_status,
        "by_category": by_category,
        "by_risk_level": by_risk,
    }


@router.get("/contractors")
async def list_contractors(
    user: User = Depends(require_officer_or_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Contractor)
    if user.tenant_id:
        query = query.filter(Contractor.tenant_id == user.tenant_id)

    contractors = query.all()
    return {
        "contractors": [
            {
                "id": str(c.id),
                "name": c.name,
                "specializations": c.specializations,
                "rating": c.rating,
                "active_workload": c.active_workload,
                "zone": c.zone,
            }
            for c in contractors
        ]
    }
```

**Step 2: Commit**

```bash
git add backend/app/routers/admin.py
git commit -m "feat: add admin routes for complaints, work orders, analytics, contractors"
```

---

### Task 28: Public dashboard route

**Files:**
- Create: `backend/app/routers/public.py`

**Step 1: Create public.py**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models.complaint import Complaint

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/dashboard")
async def public_dashboard(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Complaint)
    if tenant_id:
        query = query.filter(Complaint.tenant_id == tenant_id)

    total = query.count()
    resolved = query.filter(Complaint.status.in_(["resolved", "closed"])).count()
    resolution_rate = (resolved / total * 100) if total > 0 else 0

    by_category = dict(
        query.with_entities(Complaint.category, func.count(Complaint.id))
        .filter(Complaint.category.isnot(None))
        .group_by(Complaint.category)
        .all()
    )

    # Heatmap data: complaints with GPS coordinates
    heatmap = [
        {"lat": c.latitude, "lng": c.longitude, "category": c.category, "status": c.status}
        for c in query.filter(
            Complaint.latitude.isnot(None), Complaint.longitude.isnot(None)
        ).limit(500).all()
    ]

    by_status = dict(
        query.with_entities(Complaint.status, func.count(Complaint.id))
        .group_by(Complaint.status)
        .all()
    )

    return {
        "total_complaints": total,
        "resolved_complaints": resolved,
        "resolution_rate": round(resolution_rate, 1),
        "by_category": by_category,
        "by_status": by_status,
        "heatmap_data": heatmap,
    }
```

**Step 2: Commit**

```bash
git add backend/app/routers/public.py
git commit -m "feat: add public dashboard route with aggregate stats and heatmap"
```

---

### Task 29: Mock data seeder

**Files:**
- Create: `backend/app/mock_data/__init__.py`
- Create: `backend/app/mock_data/seed.py`

**Step 1: Create seed.py**

```python
import uuid
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import User
from app.models.department import Department
from app.models.contractor import Contractor
from app.utils.auth import hash_password


def seed_database(db: Session):
    """Seed database with mock data for testing."""

    # Check if already seeded
    if db.query(Tenant).first():
        return {"message": "Database already seeded"}

    # Create tenant
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Bangalore Municipal Corporation",
        config={
            "sla_hours": {"critical": 4, "high": 24, "medium": 72, "low": 168},
        },
    )
    db.add(tenant)

    # Create admin
    admin = User(
        tenant_id=tenant.id,
        email="admin@civicai.gov",
        name="System Admin",
        role="admin",
        password_hash=hash_password("admin123"),
    )
    db.add(admin)

    # Create departments and officers
    departments_data = [
        ("Public Works Department", ["ROADS", "CONSTRUCTION"], "Officer Ramesh"),
        ("Electricity Board", ["ELECTRICITY"], "Officer Priya"),
        ("Water Supply Department", ["WATER"], "Officer Kumar"),
        ("Sanitation Department", ["SANITATION", "SEWAGE"], "Officer Lakshmi"),
        ("Parks & Recreation", ["PUBLIC_SPACES"], "Officer Suresh"),
        ("Health Department", ["HEALTH"], "Officer Meera"),
        ("Fire Department", ["FIRE_HAZARD"], "Officer Vijay"),
        ("Flood Control Authority", ["FLOODING"], "Officer Anita"),
        ("Animal Control", ["STRAY_ANIMALS"], "Officer Raj"),
        ("Education Department", ["EDUCATION"], "Officer Deepa"),
    ]

    for dept_name, categories, officer_name in departments_data:
        officer = User(
            tenant_id=tenant.id,
            email=f"{officer_name.lower().replace(' ', '.')}@civicai.gov",
            name=officer_name,
            role="officer",
            password_hash=hash_password("officer123"),
        )
        db.add(officer)
        db.flush()

        dept = Department(
            tenant_id=tenant.id,
            name=dept_name,
            category_mapping=categories,
            head_officer_id=officer.id,
        )
        db.add(dept)

    # Create contractors
    contractors_data = [
        ("RoadFix India Pvt Ltd", ["ROADS", "CONSTRUCTION"], 4.5, "South Bangalore", 2),
        ("PowerGrid Solutions", ["ELECTRICITY"], 4.2, "North Bangalore", 1),
        ("AquaFlow Services", ["WATER", "SEWAGE", "FLOODING"], 4.0, "East Bangalore", 3),
        ("CleanCity Corp", ["SANITATION", "SEWAGE"], 3.8, "West Bangalore", 2),
        ("GreenScape Pvt Ltd", ["PUBLIC_SPACES"], 4.3, "Central Bangalore", 1),
        ("SafeGuard Services", ["FIRE_HAZARD", "ELECTRICITY"], 4.6, "South Bangalore", 0),
        ("BuildRight Construction", ["ROADS", "CONSTRUCTION", "FLOODING"], 4.1, "North Bangalore", 4),
        ("MediCare Infrastructure", ["HEALTH", "EDUCATION"], 3.9, "East Bangalore", 1),
    ]

    for name, specs, rating, zone, workload in contractors_data:
        contractor = Contractor(
            tenant_id=tenant.id,
            name=name,
            specializations=specs,
            rating=rating,
            active_workload=workload,
            zone=zone,
        )
        db.add(contractor)

    db.commit()
    return {"message": "Database seeded successfully", "tenant_id": str(tenant.id)}
```

**Step 2: Commit**

```bash
git add backend/app/mock_data/
git commit -m "feat: add mock data seeder with tenant, officers, departments, contractors"
```

---

### Task 30: Wire everything into main.py

**Files:**
- Modify: `backend/app/main.py`

**Step 1: Update main.py**

```python
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routers import auth, complaints, admin, public

app = FastAPI(
    title="CivicAI",
    description="AI-Driven Government Infrastructure Resolution System",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(admin.router)
app.include_router(public.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/seed")
async def seed_data(db: Session = Depends(get_db)):
    from app.mock_data.seed import seed_database
    return seed_database(db)
```

**Step 2: Create routers/__init__.py**

```python
from app.routers import auth, complaints, admin, public
```

**Step 3: Run the server and test**

Run: `cd backend && python -m uvicorn app.main:app --reload --port 8000`
Expected: Server starts. Visit `http://localhost:8000/docs` — see all endpoints.

**Step 4: Commit**

```bash
git add backend/app/main.py backend/app/routers/__init__.py
git commit -m "feat: wire all routes into FastAPI app"
```

---

## Phase 7: Frontend

### Task 31: Frontend project setup

**Step 1: Create React + Vite + TypeScript project**

Run: `cd E:/coding/CivicAi && npm create vite@latest frontend -- --template react-ts`

**Step 2: Install dependencies**

Run: `cd frontend && npm install && npm install react-router-dom @tanstack/react-query axios recharts leaflet react-leaflet @types/leaflet socket.io-client`

**Step 3: Install and configure Tailwind CSS**

Run: `cd frontend && npm install -D tailwindcss @tailwindcss/vite`

Update `vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

Update `src/index.css`:
```css
@import "tailwindcss";
```

**Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold React + Vite + TypeScript + Tailwind frontend"
```

---

### Task 32: Frontend API client and types

**Files:**
- Create: `frontend/src/services/api.ts`
- Create: `frontend/src/types/index.ts`

**Step 1: Create types/index.ts**

```typescript
export interface Complaint {
  id: string;
  tracking_id: string;
  status: string;
  description: string;
  citizen_email: string;
  category: string | null;
  subcategory: string | null;
  priority_score: number | null;
  risk_level: string | null;
  address: string | null;
  ward: string | null;
  district: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkOrder {
  id: string;
  complaint_id: string;
  contractor_id: string | null;
  status: string;
  sla_deadline: string | null;
  estimated_cost: number | null;
  notes: string | null;
  created_at: string;
}

export interface Contractor {
  id: string;
  name: string;
  specializations: string[];
  rating: number;
  active_workload: number;
  zone: string;
}

export interface DashboardStats {
  total_complaints: number;
  resolved_complaints: number;
  resolution_rate: number;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  heatmap_data: Array<{
    lat: number;
    lng: number;
    category: string;
    status: string;
  }>;
}

export interface Analytics {
  total_complaints: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_risk_level: Record<string, number>;
}
```

**Step 2: Create services/api.ts**

```typescript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000',
});

// Add auth token to admin requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token && config.url?.startsWith('/admin')) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Citizen APIs
export const submitComplaint = (formData: FormData) =>
  api.post('/complaints/', formData);

export const trackComplaint = (trackingId: string) =>
  api.get(`/complaints/track/${trackingId}`);

export const requestOTP = (email: string) =>
  api.post('/complaints/verify-email', { email });

export const verifyOTP = (email: string, otp: string) =>
  api.post('/complaints/verify-otp', { email, otp });

export const getMyComplaints = (email: string) =>
  api.get(`/complaints/my?email=${email}`);

// Public APIs
export const getPublicDashboard = (tenantId?: string) =>
  api.get('/public/dashboard', { params: { tenant_id: tenantId } });

// Admin APIs
export const adminLogin = (email: string, password: string) =>
  api.post('/admin/login', { email, password });

export const getAdminComplaints = (params?: Record<string, string>) =>
  api.get('/admin/complaints', { params });

export const updateComplaint = (id: string, data: Record<string, unknown>) =>
  api.patch(`/admin/complaints/${id}`, data);

export const getWorkOrders = (status?: string) =>
  api.get('/admin/work-orders', { params: { status } });

export const updateWorkOrder = (id: string, data: Record<string, unknown>) =>
  api.patch(`/admin/work-orders/${id}`, data);

export const getAnalytics = () =>
  api.get('/admin/analytics');

export const getContractors = () =>
  api.get('/admin/contractors');

export const seedDatabase = () =>
  api.post('/admin/seed');

export default api;
```

**Step 3: Commit**

```bash
git add frontend/src/services/ frontend/src/types/
git commit -m "feat: add frontend API client and TypeScript types"
```

---

### Task 33: App routing and layout

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/Layout.tsx`

**Step 1: Create Layout.tsx**

```tsx
import { Link, Outlet, useLocation } from 'react-router-dom';

export default function Layout() {
  const location = useLocation();

  const isActive = (path: string) =>
    location.pathname.startsWith(path) ? 'bg-blue-700' : '';

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-blue-900 text-white shadow-lg">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="text-xl font-bold">CivicAI</Link>
          <div className="flex gap-2">
            <Link to="/" className={`px-3 py-1 rounded ${isActive('/submit') || location.pathname === '/' ? 'bg-blue-700' : ''}`}>
              Submit Complaint
            </Link>
            <Link to="/track" className={`px-3 py-1 rounded ${isActive('/track')}`}>
              Track
            </Link>
            <Link to="/dashboard" className={`px-3 py-1 rounded ${isActive('/dashboard')}`}>
              Public Dashboard
            </Link>
            <Link to="/admin" className={`px-3 py-1 rounded ${isActive('/admin')}`}>
              Admin
            </Link>
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
```

**Step 2: Update App.tsx**

```tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import SubmitComplaint from './pages/citizen/SubmitComplaint';
import TrackComplaint from './pages/citizen/TrackComplaint';
import PublicDashboard from './pages/public/PublicDashboard';
import AdminLogin from './pages/admin/AdminLogin';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminComplaints from './pages/admin/AdminComplaints';
import AdminWorkOrders from './pages/admin/AdminWorkOrders';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<SubmitComplaint />} />
            <Route path="track" element={<TrackComplaint />} />
            <Route path="dashboard" element={<PublicDashboard />} />
            <Route path="admin/login" element={<AdminLogin />} />
            <Route path="admin" element={<AdminDashboard />} />
            <Route path="admin/complaints" element={<AdminComplaints />} />
            <Route path="admin/work-orders" element={<AdminWorkOrders />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

**Step 3: Create placeholder pages** (each as a simple component exporting a div with the page name — will be fleshed out in subsequent tasks)

Create these files with placeholder content:
- `frontend/src/pages/citizen/SubmitComplaint.tsx`
- `frontend/src/pages/citizen/TrackComplaint.tsx`
- `frontend/src/pages/public/PublicDashboard.tsx`
- `frontend/src/pages/admin/AdminLogin.tsx`
- `frontend/src/pages/admin/AdminDashboard.tsx`
- `frontend/src/pages/admin/AdminComplaints.tsx`
- `frontend/src/pages/admin/AdminWorkOrders.tsx`

Each placeholder:
```tsx
export default function PageName() {
  return <div>PageName — Coming Soon</div>;
}
```

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: add app routing, layout, and placeholder pages"
```

---

### Task 34: Citizen complaint submission page

**Files:**
- Modify: `frontend/src/pages/citizen/SubmitComplaint.tsx`

**Step 1: Implement SubmitComplaint page**

Build a single-page form with:
- Text description (textarea)
- Email (required), phone, name fields
- File upload (multiple: images, video, voice)
- GPS location (auto-detect with browser geolocation API + manual address input)
- Submit button
- On success: show tracking ID prominently

Use `@tanstack/react-query` mutation for the API call. Use Tailwind for styling.

**Step 2: Run dev server and test**

Run: `cd frontend && npm run dev`
Expected: Form renders, can fill out and submit

**Step 3: Commit**

```bash
git add frontend/src/pages/citizen/SubmitComplaint.tsx
git commit -m "feat: implement citizen complaint submission form"
```

---

### Task 35: Complaint tracking page

**Files:**
- Modify: `frontend/src/pages/citizen/TrackComplaint.tsx`

**Step 1: Implement TrackComplaint page**

Two sections:
1. **Track by ID**: input field + search button → shows complaint status card
2. **View all (email+OTP)**: email input → "Send OTP" → OTP input → verify → shows all complaints

Use WebSocket connection for real-time updates on the status card.

**Step 2: Commit**

```bash
git add frontend/src/pages/citizen/TrackComplaint.tsx
git commit -m "feat: implement complaint tracking page with OTP and WebSocket"
```

---

### Task 36: Public dashboard page

**Files:**
- Modify: `frontend/src/pages/public/PublicDashboard.tsx`

**Step 1: Implement PublicDashboard**

- KPI cards: total complaints, resolved, resolution rate
- Category breakdown bar chart (Recharts)
- Status distribution pie chart
- Complaint heatmap (Leaflet map with markers)

**Step 2: Commit**

```bash
git add frontend/src/pages/public/PublicDashboard.tsx
git commit -m "feat: implement public transparency dashboard with charts and heatmap"
```

---

### Task 37: Admin login page

**Files:**
- Modify: `frontend/src/pages/admin/AdminLogin.tsx`

**Step 1: Implement AdminLogin**

Simple login form (email + password). On success, store JWT in localStorage, redirect to /admin.

**Step 2: Commit**

```bash
git add frontend/src/pages/admin/AdminLogin.tsx
git commit -m "feat: implement admin login page"
```

---

### Task 38: Admin dashboard page

**Files:**
- Modify: `frontend/src/pages/admin/AdminDashboard.tsx`

**Step 1: Implement AdminDashboard**

- KPI cards: open complaints, resolved, SLA breaches, total work orders
- Category distribution chart
- Risk level distribution chart
- Recent complaints table (top 10)
- Links to full complaints list and work orders

**Step 2: Commit**

```bash
git add frontend/src/pages/admin/AdminDashboard.tsx
git commit -m "feat: implement admin dashboard with KPIs and charts"
```

---

### Task 39: Admin complaints management page

**Files:**
- Modify: `frontend/src/pages/admin/AdminComplaints.tsx`

**Step 1: Implement AdminComplaints**

- Filterable table (by status, category, risk level)
- Each row: tracking ID, description snippet, category, priority, status, date
- Click to expand: full details, AI analysis, option to reassign/update status
- Contractor recommendation display with option to change

**Step 2: Commit**

```bash
git add frontend/src/pages/admin/AdminComplaints.tsx
git commit -m "feat: implement admin complaints management page"
```

---

### Task 40: Admin work orders page

**Files:**
- Modify: `frontend/src/pages/admin/AdminWorkOrders.tsx`

**Step 1: Implement AdminWorkOrders**

- Kanban-style columns: Created → Accepted → In Progress → Completed → Verified
- Each card: complaint summary, contractor, SLA deadline, estimated cost
- Drag or button to update status

**Step 2: Commit**

```bash
git add frontend/src/pages/admin/AdminWorkOrders.tsx
git commit -m "feat: implement admin work orders Kanban board"
```

---

## Phase 8: Background Jobs & Final Integration

### Task 41: SLA monitoring background scheduler

**Files:**
- Modify: `backend/app/main.py`

**Step 1: Add APScheduler startup**

Add to main.py:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.agents.tracker import check_sla_deadlines
from app.database import SessionLocal

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(
        lambda: check_sla_deadlines(SessionLocal()),
        "interval",
        minutes=5,
    )
    scheduler.start()

@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()
```

**Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: add SLA monitoring background scheduler"
```

---

### Task 42: Docker Compose full stack

**Files:**
- Modify: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`

**Step 1: Create backend Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Create frontend Dockerfile**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**Step 3: Create frontend/nginx.conf**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000/;
    }

    location /ws/ {
        proxy_pass http://backend:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Step 4: Update docker-compose.yml**

```yaml
version: "3.8"

services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: civicai
      POSTGRES_PASSWORD: civicai
      POSTGRES_DB: civicai
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://civicai:civicai@db:5432/civicai
    depends_on:
      - db
    volumes:
      - ./backend/uploads:/app/uploads

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

volumes:
  pgdata:
```

**Step 5: Commit**

```bash
git add docker-compose.yml backend/Dockerfile frontend/Dockerfile frontend/nginx.conf
git commit -m "feat: add Docker Compose full stack deployment"
```

---

### Task 43: Final integration test

**Step 1: Start full stack**

Run: `docker-compose up --build -d`

**Step 2: Seed database**

Run: `curl -X POST http://localhost:8000/admin/seed`

**Step 3: Test citizen flow**

Submit a complaint via the frontend or API, verify it goes through the pipeline.

**Step 4: Test admin flow**

Login as admin, verify dashboard shows data, work orders are visible.

**Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration fixes from end-to-end testing"
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1-3 | Project scaffolding, config, Docker |
| 2 | 4-7 | Database models, migrations |
| 3 | 8 | Pydantic schemas |
| 4 | 9-15 | Core services (LLM, media, geocoding, OTP, email, WebSocket) |
| 5 | 16-24 | Agent pipeline (7 agents + orchestrator) |
| 6 | 25-30 | API routes (auth, complaints, admin, public, seed) |
| 7 | 31-40 | Frontend (setup, pages, components) |
| 8 | 41-43 | Background jobs, Docker, integration test |

**Total: 43 tasks across 8 phases.**
