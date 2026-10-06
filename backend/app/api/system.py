from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.services.seed import seed_database

router = APIRouter(tags=["system"])

VERSION = "2.0.0-phase0"


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": VERSION}


@router.post("/admin/seed")
async def seed(db: Session = Depends(get_db)) -> dict:
    """Development-only. Populates demo tenants, departments and contractors.

    This endpoint writes to the database and Phase 0 has no auth layer yet, so it
    is gated on the environment rather than on a token. Officer/admin JWT auth
    arrives with the real API in a later phase; until then this guard is what
    keeps an unauthenticated writer off a non-development deployment.
    """
    if settings.environment != "development":
        raise HTTPException(status_code=404, detail="Not found")
    return seed_database(db)
