from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import get_db, SessionLocal
from app.routers import auth, complaints, admin, public
from app.agents.tracker import check_sla_deadlines

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        lambda: check_sla_deadlines(SessionLocal()),
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
