import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os

# Absolute path to this file's parent (app/) then parent (backend/)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

from app.config import settings
from app.database import get_db, SessionLocal, create_tables
from app.routers import auth, complaints, admin, public
from app.agents.tracker import check_sla_deadlines
from app.agents.cluster import run_cluster_detection as _cluster_detect
from app.agents.briefing import generate_daily_briefing
from app.models import *  # noqa: F401,F403 - ensure all models are loaded
from app.models.daily_briefing import DailyBriefing  # noqa: F401 - register model
from app.utils.auth import require_officer_or_admin

scheduler = AsyncIOScheduler()


async def run_sla_check():
    db = SessionLocal()
    try:
        await check_sla_deadlines(db)
    finally:
        db.close()


async def run_cluster_detection():
    db = SessionLocal()
    try:
        await _cluster_detect(db)
    finally:
        db.close()


async def run_daily_briefing():
    db = SessionLocal()
    try:
        await generate_daily_briefing(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (for SQLite dev mode)
    create_tables()
    scheduler.add_job(run_sla_check, "interval", minutes=5)
    scheduler.add_job(run_cluster_detection, "interval", hours=1)
    scheduler.add_job(run_daily_briefing, "cron", hour=8, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="CivicAI",
    description="AI-Driven Government Infrastructure Resolution System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(admin.router)
app.include_router(public.router)

# Serve uploaded media files
os.makedirs(str(UPLOADS_DIR), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/media/{filename}")
async def serve_media(filename: str):
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    import mimetypes
    file_path = UPLOADS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    mime, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(str(file_path), media_type=mime or "application/octet-stream")


@app.post("/admin/seed")
async def seed_data(db: Session = Depends(get_db)):
    from app.mock_data.seed import seed_database
    return seed_database(db)
