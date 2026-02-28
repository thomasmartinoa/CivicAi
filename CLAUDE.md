# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CivicAI is an AI-driven government infrastructure complaint resolution system. Citizens submit complaints (text, images, voice, GPS), which are processed through a 7-agent AI pipeline that validates, classifies, risk-assesses, routes to departments, and generates work orders with SLA tracking.

## Architecture

**Backend**: Python 3.14 + FastAPI + SQLAlchemy ORM + SQLite (dev) / PostgreSQL (prod)
**Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + React Query + Recharts + Leaflet
**AI**: Google Gemini (gemini-2.5-flash-lite) with keyword-based fallback when API is unavailable

### Multi-Agent Pipeline (`backend/app/agents/`)

Complaints flow through 7 sequential agents via `ComplaintPipeline`:
1. **IntakeAgent** - Media processing (speech-to-text, image analysis), reverse geocoding via Nominatim
2. **ValidationAgent** - LLM validates if complaint is infrastructure-related
3. **ClassificationAgent** - Classifies into 12 categories (ROADS, ELECTRICITY, WATER, etc.)
4. **RiskAssessorAgent** - Scores 0-100 across safety, urgency, population impact
5. **RoutingAgent** - Maps to department + selects best contractor by specialization/rating/workload
6. **WorkOrderAgent** - Creates work order with SLA deadline and cost estimate
7. **TrackingAgent** - Sends notifications, WebSocket broadcasts

All agents extend `BaseAgent` with `async process(context, db)` signature. `PipelineContext` dataclass carries state between agents.

### Key Design Decisions

- **No citizen login**: Citizens use email + OTP to view past complaints
- **JWT auth for admin/officer only** - no contractor login
- **Multi-tenant**: `tenant_id` column on all tables, auto-assigned from first tenant if not provided
- **SQLite for dev**: All model IDs use `String(36)` (not PostgreSQL UUID), arrays use `JSON` type
- **Direct bcrypt** (not passlib) for password hashing - Python 3.14 compatibility
- **State/district stored on complaints** from Nominatim geocoding for geographic filtering

## Commands

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# Seed database: POST http://localhost:8000/admin/seed
# Admin login: admin@civicai.gov / admin123
```

### Frontend
```bash
cd frontend
npm install
npm run dev          # Dev server on port 5173
npm run build        # Production build
```

### Docker (requires Docker)
```bash
docker-compose up --build
```

## Configuration

Backend config via `.env` file in `backend/` directory (loaded by `app/config.py`):
- `GEMINI_API_KEY` - Required for AI pipeline (free tier: gemini-2.5-flash-lite)
- `LLM_PROVIDER` - "gemini" (default), "anthropic", or "openai"
- `DATABASE_URL` - SQLite default: `sqlite:///./civicai.db`

## API Structure

- `POST /complaints/` - FormData (supports file uploads)
- `GET /complaints/track/{tracking_id}` - Full complaint details with media and work order
- `POST /complaints/verify-email` + `POST /complaints/verify-otp` - OTP flow
- `GET /public/dashboard` - Filterable by state, district, category
- `POST /admin/login` - JWT auth
- `GET /admin/complaints`, `GET /admin/work-orders`, `GET /admin/analytics` - Auth required
- `GET /health` - Health check
- `/uploads/*` - Static file serving for uploaded media

## File Serving

Uploaded files are saved to `backend/uploads/` with paths stored as `uploads/filename.ext`. FastAPI serves them via `StaticFiles` mount at `/uploads`.
