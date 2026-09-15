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
    WORK_ORDER = "work_order"


# Model tiering: cheap models for the high-volume mechanical steps, a stronger
# one where the output is prose a human reads or the judgement is high-stakes.
# Configured here rather than at the call sites so an eval sweep can vary it.
# Risk scoring sets the SLA and is the most judgement-heavy step, so per the
# design spec it gets the strong tier alongside narration, not flash-lite.
#
# NOTE — import-time snapshot: this dict reads `settings` once, at import
# time, unlike `available_providers()` below which reads `settings` fresh on
# every call. `monkeypatch.setattr(settings, "gemini_model", ...)` in a test
# silently does nothing to this dict, even though the same pattern works
# against `available_providers()`. An eval sweep that wants to vary a task's
# model tier must mutate `TASK_MODEL` directly, not `settings`.
TASK_MODEL: dict[Task, str] = {
    Task.VALIDATE: settings.gemini_model,
    Task.CLASSIFY: settings.gemini_model,
    Task.ASSESS_RISK: settings.gemini_model_strong,
    Task.VISION: settings.gemini_model,
    Task.NARRATE: settings.gemini_model_strong,
    Task.WORK_ORDER: settings.gemini_model,
}

# One ceiling for the whole process. Not optional: the Gemini free tier
# rate-limits hard, and Phase 3 sweeps ~100 complaints in a run.
#
# NOTE — import-time snapshot: like TASK_MODEL above, this is built once from
# `settings` at import time, so monkeypatching `settings.llm_requests_per_second`
# after import has no effect on it.
#
# NOTE — retry/rate-limit interaction: every LLM node catches its own chain's
# exceptions and returns an `errors` update instead of raising, so the graph's
# per-node `RetryPolicy(max_attempts=3)` can never fire for a chain failure —
# it only covers a node raising for some other reason. The retry that actually
# matters lives on the chain itself, via `.with_retry(stop_after_attempt=3)` in
# `build_structured` below. That stacks with `max_retries=3` on the Gemini
# client, so a single call can retry up to 9 times, each attempt queued behind
# this one shared 0.5 rps bucket. That value is tuned for Phase 3's eval sweep,
# not for a live demo: a single complaint passing through ~5 LLM nodes can
# spend well over 10s waiting in this limiter across retries. Re-check this
# against the actual Gemini free-tier RPM before any live demo.
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
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise NoModelConfigured(
                "OLLAMA_ENABLED=true but langchain-ollama is not installed. "
                "Run `pip install langchain-ollama` (it is deliberately not in "
                "requirements.txt, since most deployments only use Gemini)."
            ) from exc

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            rate_limiter=SHARED_RATE_LIMITER,
        )
    raise NoModelConfigured(f"unknown provider {provider!r}")


def build_chat_model(task: Task) -> BaseChatModel | Runnable:
    """The model for a task, with every other provider chained as a fallback.

    When there are backups, the return value is a `RunnableWithFallbacks`, not
    a `BaseChatModel` — it has no `with_structured_output` of its own and
    proxies the call to the primary model via `__getattr__` instead.
    """
    providers = available_providers()
    if not providers:
        raise NoModelConfigured(
            "No LLM provider is configured. Set GEMINI_API_KEY, or set "
            "OLLAMA_ENABLED=true with a local Ollama running, and install "
            "langchain-ollama."
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
    return get_prompt(prompt_name, prompt_version) | model.with_structured_output(
        schema
    ).with_retry(stop_after_attempt=3)
