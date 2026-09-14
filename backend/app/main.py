from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import complaints, system
from app.config import settings
from app.db.session import SessionLocal


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
    import logging

    logger = logging.getLogger(__name__)
    _guard_against_placeholder_secret_in_production()

    from app.services.execution import resume_incomplete_runs, schedule_complaint_run

    # Check if a provider is configured
    if settings.gemini_api_key is None and not settings.ollama_enabled:
        logger.warning("no LLM provider configured; AI pipeline will not function")

    try:
        for complaint_id in resume_incomplete_runs(session_factory=SessionLocal):
            logger.info("resuming interrupted complaint %s", complaint_id)
            schedule_complaint_run(complaint_id)
    except Exception:
        logger.exception("startup resume sweep failed; continuing anyway")

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
app.include_router(complaints.router)

settings.upload_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")
