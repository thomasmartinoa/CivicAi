from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All environment configuration. Read once, imported everywhere."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "development" | "staging" | "production". Guards dev-only endpoints.
    # Defaults to production so an unconfigured deployment fails CLOSED; local
    # development opts in explicitly via ENVIRONMENT=development in .env.
    environment: str = "production"

    # ── Database ──────────────────────────────────────────────
    database_url: str = "sqlite:///./civicai.db"

    # ── Auth ──────────────────────────────────────────────────
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    otp_expire_minutes: int = 10
    seed_admin_password: str = "admin123"
    seed_officer_password: str = "officer123"

    # ── LLM providers (used from Phase 1 onward) ──────────────
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash-lite"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # ── Email ─────────────────────────────────────────────────
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""

    # ── Storage ───────────────────────────────────────────────
    upload_dir: str = "./uploads"


settings = Settings()
