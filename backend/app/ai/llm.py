"""All model access lives here.

This is the only module that constructs a chat model or calls
`.with_structured_output(...)`. Nodes receive already-bound runnables, because
LangChain's fake chat models raise NotImplementedError on
with_structured_output — a node holding a raw model cannot be unit-tested.

v1 dispatched on `if provider == "gemini" / elif ...` at every call site, so
each capability was written three times and adding a provider meant three more
methods.
"""

from enum import StrEnum

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from app.ai.prompts import get_prompt
from app.config import settings


class NoModelConfigured(RuntimeError):
    """Raised when no provider is usable, instead of degrading silently."""


class Task(StrEnum):
    VALIDATE = "validate"
    CLASSIFY = "classify"
    ASSESS_RISK = "assess_risk"
    VISION = "vision"
    NARRATE = "narrate"


# Model tiering: cheap models for the high-volume mechanical steps, a stronger
# one where the output is prose a human reads. Configured here rather than at
# the call sites so an eval sweep can vary it.
TASK_MODEL: dict[Task, str] = {
    Task.VALIDATE: settings.gemini_model,
    Task.CLASSIFY: settings.gemini_model,
    Task.ASSESS_RISK: settings.gemini_model,
    Task.VISION: settings.gemini_model,
    Task.NARRATE: settings.gemini_model_strong,
}

# One ceiling for the whole process. Not optional: the Gemini free tier
# rate-limits hard, and Phase 3 sweeps ~100 complaints in a run.
SHARED_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=settings.llm_requests_per_second,
    check_every_n_seconds=0.1,
    max_bucket_size=5,
)


def available_providers() -> list[str]:
    """Usable providers, primary first. Later entries become fallbacks."""
    providers: list[str] = []
    if settings.gemini_api_key:
        providers.append("gemini")
    if settings.ollama_enabled:
        providers.append("ollama")
    return providers


def _build_one(provider: str, task: Task) -> BaseChatModel:
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=TASK_MODEL[task],
            google_api_key=settings.gemini_api_key,
            rate_limiter=SHARED_RATE_LIMITER,
            max_retries=settings.llm_max_retries,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            rate_limiter=SHARED_RATE_LIMITER,
        )
    raise NoModelConfigured(f"unknown provider {provider!r}")


def build_chat_model(task: Task) -> BaseChatModel:
    """The model for a task, with every other provider chained as a fallback."""
    providers = available_providers()
    if not providers:
        raise NoModelConfigured(
            "No LLM provider is configured. Set GEMINI_API_KEY, or set "
            "OLLAMA_ENABLED=true with a local Ollama running."
        )
    primary = _build_one(providers[0], task)
    backups = [_build_one(p, task) for p in providers[1:]]
    return primary.with_fallbacks(backups) if backups else primary


def build_structured(
    task: Task,
    schema: type[BaseModel],
    prompt_name: str,
    prompt_version: str | None = None,
) -> Runnable:
    """A prompt-to-validated-object chain, ready to hand a node.

    Nodes get one of these through `config["configurable"]`; a test passes a
    `RunnableLambda` returning a fixture instead. That seam is the whole reason
    nodes never touch a raw model.
    """
    model = build_chat_model(task)
    return get_prompt(prompt_name, prompt_version) | model.with_structured_output(schema)
