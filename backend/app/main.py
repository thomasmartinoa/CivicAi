import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import get_db, SessionLocal, create_tables
from app.routers import auth, complaints, admin, public
from app.agents.tracker import check_sla_deadlines
from app.models import *  # noqa: F401,F403 - ensure all models are loaded
from app.utils.auth import require_officer_or_admin

scheduler = AsyncIOScheduler()


async def run_sla_check():
    db = SessionLocal()
    try:
        await check_sla_deadlines(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (for SQLite dev mode)
    create_tables()
    scheduler.add_job(
        run_sla_check,
        "interval",
        minutes=5,
    )
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
upload_dir = settings.upload_dir
os.makedirs(upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/seed")
async def seed_data(db: Session = Depends(get_db)):
    from app.mock_data.seed import seed_database
    return seed_database(db)
