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
