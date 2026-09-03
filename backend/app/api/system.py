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
