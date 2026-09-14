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
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_model_strong: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_enabled: bool = False
    # Requests per second ceiling shared by every task. The Gemini free tier
    # rate-limits aggressively and a 100-item eval sweep will hit it.
    llm_requests_per_second: float = 0.5
    llm_max_retries: int = 3

    # ── Email ─────────────────────────────────────────────────
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""

    # ── RAG ───────────────────────────────────────────────
    embedding_model: str = "gemini-embedding-001"
    rag_index_dir: str = "./data/index"

    # ── Storage ───────────────────────────────────────────────
    upload_dir: str = "./uploads"

    @property
    def upload_path(self) -> Path:
        """upload_dir anchored to the backend directory when relative, so store,
        serve and the vision adapter resolve it identically regardless of CWD."""
        raw = Path(self.upload_dir)
        return raw if raw.is_absolute() else (BACKEND_DIR / raw).resolve()


settings = Settings()
