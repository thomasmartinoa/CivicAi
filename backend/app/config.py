from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All environment configuration. Read once, imported everywhere."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "development" | "staging" | "production". Guards dev-only endpoints.
    # Defaults to production so an unconfigured deployment fails CLOSED; local
    # development opts in explicitly via ENVIRONMENT=development in .env.
    environment: Literal["development", "staging", "production"] = "production"

    # ── Database ──────────────────────────────────────────────
    database_url: str = "sqlite:///./civicai.db"

    # ── Auth ──────────────────────────────────────────────────
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    otp_expire_minutes: int = 10
    seed_admin_password: str = "admin123"
    seed_officer_password: str = "officer123"

    # ── LLM providers ─────────────────────────────────────────
    gemini_api_key: str | None = None
    # Checked against the live model list on 2026-09-27: the 2.5 names these
    # defaults used until then return 404 NOT_FOUND ("no longer available to new
    # users"), and the API's own deprecation notice names 3.5 as the migration
    # target. Model ids expire; the smoke test in Phase 3's plan is what catches
    # it, since every unit test uses a fake model.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_model_strong: str = "gemini-3.5-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_enabled: bool = False
    # Requests per second ceiling shared by every task. The Gemini free tier
    # rate-limits aggressively and a 100-item eval sweep will hit it.
    llm_requests_per_second: float = 0.5
    llm_max_retries: int = 3
    # A stalled connection must fail rather than hang. Without this an eval sweep
    # sat on one request for five minutes with no response and no retry, and a
    # complaint's background run would have waited for ever -- never completing and
    # never failing, which is the worst of both.
    llm_timeout_seconds: int = 60

    # ── Email ─────────────────────────────────────────────────
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""

    # ── RAG ───────────────────────────────────────────────
    embedding_model: str = "gemini-embedding-001"
    rag_index_dir: str = "./data/index"
    # A near-duplicate prompt reuses the previous completion instead of paying
    # for another model call. 0.95 cosine is tight enough that only genuine
    # restatements hit; see app/ai/cache.py.
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.95
    # The SLA monitor and anything else on a timer. Off in tests, which run
    # the app's lifespan for real and must not leave a scheduler behind.
    background_jobs_enabled: bool = True
    # Semantic clustering: how close two reports must be in space and in meaning
    # to be one job, and how many sites make a cluster worth grouping. v1 used a
    # ~1 km grid and required identical category labels.
    cluster_radius_km: float = 0.5
    cluster_similarity_threshold: float = 0.82
    cluster_min_size: int = 3
    # Which scheduled jobs run, and when the officer's briefing is written.
    # background_jobs_enabled is the master switch over all of them.
    cluster_detection_enabled: bool = True
    briefing_enabled: bool = True
    cases_refresh_enabled: bool = True
    briefing_hour: int = 8
    # Where the operator wrote the per-token prices they were actually quoted.
    # Empty by default and no rates are ever assumed: an invented price is the
    # number most likely to be lifted into a README and quoted at somebody.
    eval_cost_rates_file: str = ""
    # LangSmith tracing. Off by default, and ignored without a key: a flag with no
    # key would make every call attempt a trace and fail. The trace carries
    # internal ids and AI outputs only -- see app/ai/observability.py on what is
    # deliberately left out.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "civicai"

    # ── Storage ───────────────────────────────────────────────
    upload_dir: str = "./uploads"

    @property
    def upload_path(self) -> Path:
        """upload_dir anchored to the backend directory when relative, so store,
        serve and the vision adapter resolve it identically regardless of CWD."""
        raw = Path(self.upload_dir)
        return raw if raw.is_absolute() else (BACKEND_DIR / raw).resolve()

    @property
    def eval_cost_rates_path(self) -> Path | None:
        """The rates file, anchored like rag_index_path, or None when unset."""
        if not self.eval_cost_rates_file:
            return None
        raw = Path(self.eval_cost_rates_file)
        return raw if raw.is_absolute() else (BACKEND_DIR / raw).resolve()

    @property
    def rag_index_path(self) -> Path:
        """rag_index_dir anchored to the backend directory when relative, so the
        ingest CLI and the API process resolve it identically regardless of CWD."""
        raw = Path(self.rag_index_dir)
        return raw if raw.is_absolute() else (BACKEND_DIR / raw).resolve()


settings = Settings()
