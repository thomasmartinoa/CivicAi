from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import system
from app.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"


def _guard_against_placeholder_secret_in_production() -> None:
    """Refuse to boot with the placeholder SECRET_KEY in production.

    SECRET_KEY signs real JWTs once auth lands. `environment` defaults to
    "production" (fail closed) and `secret_key` defaults to a public,
    well-known placeholder, so this is intentionally NOT a pydantic
    validator on Settings: that field defaults to the exact combination
    this guards against, and Settings() is built once, eagerly, at import
    time — a validator there would make the module itself unimportable
    for any process (including the test suite) that has not configured a
    real secret. Checking at startup instead means the app still imports
    everywhere, but a real deployment that boots unconfigured fails loudly.
    """
    if settings.environment == "production" and settings.secret_key == "change-me-in-production":
        raise RuntimeError("SECRET_KEY must be set when ENVIRONMENT=production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _guard_against_placeholder_secret_in_production()
    # Otherwise empty for now — Phase 1 adds the scheduler here.
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
