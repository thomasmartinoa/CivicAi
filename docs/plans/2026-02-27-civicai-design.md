# CivicAI System Design

## Overview

Autonomous AI-Driven Government Infrastructure Resolution System that automates the end-to-end lifecycle of public infrastructure complaints using a multi-agent AI architecture.

## Decisions

- **Backend**: Python + FastAPI
- **Architecture**: Monolithic pipeline (agents as Python classes)
- **Database**: PostgreSQL (multi-tenant via tenant_id column)
- **AI**: Real LLM calls (Claude/OpenAI) for classification, risk assessment, analysis
- **Frontend**: React + Vite + Tailwind CSS (citizen portal + admin dashboard + public dashboard)
- **Inputs**: Text, voice (speech-to-text), image, GPS, video (Street View verification for road/physical issues)
- **Notifications**: WebSocket (real-time) + Email (milestones)
- **Multi-tenant**: Yes, from the start

## Infrastructure Categories

ROADS, ELECTRICITY, WATER, SANITATION, PUBLIC SPACES, EDUCATION, HEALTH, FLOODING, FIRE HAZARD, CONSTRUCTION, STRAY ANIMALS, SEWAGE

Non-infrastructure complaints are rejected.

## Auth Model

- **Citizens**: No login. Submit complaints freely. Track via complaint ID or email+OTP for full history.
- **Officers**: JWT login. Review complaints, approve/change contractor recommendations, manage work orders.
- **Admins**: JWT login. Full system access, analytics, tenant management.
- **Contractors**: No login. Exist as database records. Officers assign and manage on their behalf.

## System Architecture

```
Citizens ──▶ Citizen Portal (React) ──▶ FastAPI Backend ──▶ PostgreSQL
Public   ──▶ Public Dashboard (React) ──▶       │
Officers ──▶ Admin Dashboard (React)  ──▶       │
                                                 │
                                    ┌────────────┘
                                    ▼
                            Complaint Pipeline
                            (7 Sequential Agents)
                                    │
                            ┌───────┼───────┐
                            ▼       ▼       ▼
                          LLM    WebSocket  Email
                        Service   Server   Service
```

## Agent Pipeline

Each agent implements `BaseAgent.process(context) -> context`.

### 1. Intake Agent
- Accepts raw complaint (text, voice, image, video, GPS)
- Voice → speech-to-text (Whisper API)
- Image/Video → store files, extract metadata
- GPS → reverse geocode to address
- Output: structured ComplaintInput

### 2. Validation & Structuring Agent
- Validates sufficient info (description, location)
- LLM extracts structured fields: what, where, when, severity keywords
- Rejects non-infrastructure complaints
- Output: ValidatedComplaint

### 3. Classification Agent
- LLM classifies into 12 categories + subcategory
- Confidence score — below threshold flags for human review
- Output: ClassifiedComplaint

### 4. Risk & Priority Agent
- Risk level: Critical / High / Medium / Low
- Scoring (0-100) based on: category severity, population impact, safety risk, media evidence
- Video/image comparison against Street View for road/physical issues
- Output: PrioritizedComplaint

### 5. Routing Agent
- Maps category → government department (mock DB)
- Determines jurisdiction: Ward → Block → District → City via GPS/address
- Recommends contractor via scoring model (rating, proximity, workload, specialization)
- Output: RoutedComplaint

### 6. Work Order Agent
- Generates digital work order
- Sets SLA: Critical=4h, High=24h, Medium=72h, Low=7d
- Output: WorkOrder persisted to DB

### 7. Tracking & Escalation Agent
- Background scheduler monitors SLA deadlines
- 75% SLA elapsed → notify supervisor
- SLA breached → escalate to next jurisdiction level
- Sends status updates via WebSocket + email
- Output: status change events

## Complaint Workflow

```
Complaint submitted → Pipeline processes → System recommends contractor
→ Officer reviews & approves/changes → Work order created
→ Officer tracks progress → Officer marks complete
```

## Data Model

### Tenant
- id, name, config (SLA rules, departments), created_at

### User
- id, tenant_id, email, role (citizen/officer/admin), name, phone, department_id?

### Complaint
- id, tenant_id, citizen_email, citizen_phone, tracking_id
- status: submitted → validated → classified → prioritized → assigned → in_progress → resolved → closed
- description, category, subcategory, priority_score, risk_level
- location_gps (lat/lng), address, ward, block, district
- media[] (files), classification_confidence, ai_analysis (JSON)
- created_at, updated_at

### WorkOrder
- id, complaint_id, tenant_id, contractor_id, officer_id
- status: created → accepted → in_progress → completed → verified
- sla_deadline, estimated_cost, materials, notes
- created_at, completed_at

### Department
- id, tenant_id, name, category_mapping[], head_officer_id

### Contractor
- id, tenant_id, name, specializations[], rating, active_workload, zone

### Escalation
- id, complaint_id, from_level, to_level, reason, escalated_at

### Notification
- id, user_id, complaint_id, type (email/websocket), message, sent_at

## API Endpoints

### Citizen (no auth)
- `POST /complaints` — submit (email + phone required, multipart)
- `GET /complaints/track/{tracking_id}` — check single complaint
- `POST /complaints/verify-email` — send OTP
- `POST /complaints/verify-otp` — verify OTP, get session
- `GET /complaints/my` — list all (requires OTP session)
- `WebSocket /ws/complaints/{tracking_id}` — real-time updates

### Public (no auth)
- `GET /public/dashboard` — aggregate stats, heatmap data

### Admin (JWT)
- `POST /admin/login`
- `GET /admin/complaints` — filtered by department/status/priority
- `PATCH /admin/complaints/{id}` — update status, reassign
- `GET /admin/work-orders` — work order dashboard
- `PATCH /admin/work-orders/{id}` — update progress
- `GET /admin/analytics` — infrastructure analytics
- `GET /admin/contractors` — contractor list with ratings/workload
- `POST /admin/seed` — seed mock data

### System
- `GET /health`

## Frontend Pages

### Citizen Portal
- Single-page complaint form (describe → upload media → confirm location → submit)
- Track by ID or email+OTP
- Real-time status via WebSocket

### Public Dashboard
- City-wide stats (total complaints, resolution rate, avg time)
- Category breakdown chart
- Heatmap of active complaints

### Admin Dashboard
- KPI cards (open/resolved/SLA breaches)
- Complaints table (filterable)
- Work orders (Kanban-style)
- Analytics charts (resolution time, category distribution, contractor performance)
- Contractor management (ratings, workload, history)

## Tech Dependencies

### Backend
- FastAPI, Uvicorn, SQLAlchemy, Alembic, Pydantic
- anthropic or openai SDK for LLM
- openai (Whisper) for speech-to-text
- Pillow, python-multipart for media
- python-jose (JWT), passlib (passwords)
- APScheduler for SLA monitoring

### Frontend
- React 18, Vite, TypeScript, Tailwind CSS
- React Router, TanStack Query
- Recharts or Chart.js
- Leaflet or Mapbox for heatmap
- Socket.io client

### Infrastructure
- Docker Compose (PostgreSQL + backend + frontend)
- Multi-tenancy via tenant_id on all tables

## Project Structure

```
civicai/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── pipeline.py
│   │   │   ├── intake.py
│   │   │   ├── validator.py
│   │   │   ├── classifier.py
│   │   │   ├── risk_assessor.py
│   │   │   ├── router.py
│   │   │   ├── work_order.py
│   │   │   └── tracker.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/
│   │   │   ├── llm.py
│   │   │   ├── media.py
│   │   │   ├── geocoding.py
│   │   │   ├── email.py
│   │   │   ├── otp.py
│   │   │   └── websocket.py
│   │   ├── mock_data/
│   │   └── utils/
│   ├── alembic/
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── citizen/
│   │   │   ├── admin/
│   │   │   └── public/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
└── README.md
```
