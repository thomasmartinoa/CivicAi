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
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from app.ai.prompts import get_prompt
from app.config import settings

if TYPE_CHECKING:
    from app.ai.cache import SemanticCache


class NoModelConfigured(RuntimeError):
    """Raised when no provider is usable, instead of degrading silently."""


class Task(StrEnum):
    VALIDATE = "validate"
    CLASSIFY = "classify"
    INVESTIGATE = "investigate"
    ASSESS_RISK = "assess_risk"
    VISION = "vision"
    NARRATE = "narrate"
    EMAIL_DRAFT = "email_draft"
    WORK_ORDER = "work_order"
    OFFICER_CHAT = "officer_chat"


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
    Task.INVESTIGATE: settings.gemini_model_strong,
    Task.ASSESS_RISK: settings.gemini_model_strong,
    Task.VISION: settings.gemini_model,
    Task.NARRATE: settings.gemini_model_strong,
    # Prose an officer signs their name to, so the strong tier like NARRATE.
    Task.EMAIL_DRAFT: settings.gemini_model_strong,
    Task.WORK_ORDER: settings.gemini_model,
    # The flash tier, despite being conversational prose. A ReAct turn is several
    # calls, and the strong tier's free quota is 20 a DAY — an officer asking four
    # questions would exhaust it before lunch. Tool-call selection is a mechanical
    # choice among six options, which is what flash is good at.
    Task.OFFICER_CHAT: settings.gemini_model,
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
# `build_structured` below, and that one re-invokes the whole gated runnable, so
# each of its attempts passes through this limiter.
#
# The Gemini client's own `max_retries` does NOT. It retries underneath LangChain,
# so those attempts are real HTTP requests that the limiter never sees. That made a
# 429 storm self-amplifying: the free tier allows 15 requests/minute/model, one
# gated call could fire four ungated ones, and every 429 produced more traffic
# rather than less. A validator A/B run spent most of its budget on retries of
# requests that were rejected for being too frequent. It is 0 here by default so
# that **every** HTTP request this process makes is one the limiter let through.
#
# `max_bucket_size` is 1 for the same reason: a bucket of 5 let five requests go
# instantly and then throttled, which on top of the sustained rate put the first
# minute over the quota even with no retries at all.
_RETRY_SAFE_BUCKET = 1

SHARED_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=settings.llm_requests_per_second,
    check_every_n_seconds=0.1,
    max_bucket_size=_RETRY_SAFE_BUCKET,
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
            # Without this a stalled connection hangs the caller indefinitely: a
            # node waits for ever, so the complaint neither completes nor fails.
            timeout=settings.llm_timeout_seconds,
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
    *,
    cache: "SemanticCache | None" = None,
    retries: int = 3,
) -> Runnable:
    """A prompt-to-validated-object chain, ready to hand a node.

    Nodes get one of these through `config["configurable"]`; a test passes a
    `RunnableLambda` returning a fixture instead. That seam is the whole reason
    nodes never touch a raw model.

    With a cache, the whole chain (prompt and model) sits behind the semantic
    lookup, keyed on the prompt variables — so the cache sees the same text
    whichever prompt version is active.

    `retries` is the chain's own attempt count, which stacks multiplicatively with
    `max_retries` on the client (see SHARED_RATE_LIMITER above). Production wants
    three. A caller with its own outer loop and its own fail-fast — the eval sweep —
    passes 1, because nine attempts behind a rate limiter cost over two minutes per
    item against a provider that is simply down.
    """
    if retries < 1:
        raise ValueError(f"retries must be at least 1, got {retries}")
    model = build_chat_model(task)
    chain = get_prompt(prompt_name, prompt_version) | model.with_structured_output(
        schema
    ).with_retry(stop_after_attempt=retries)
    if cache is None:
        return chain

    from app.ai.cache import with_semantic_cache

    return with_semantic_cache(chain, cache)


# One process-wide cache per (prompt name, version), built on first use. Never
# shared between chains: a classification must not be served as a risk
# assessment, nor one prompt version's answer for another's.
_CACHES: dict[tuple[str, str], "SemanticCache"] = {}


def cache_for(prompt_name: str, version: str | None = None) -> "SemanticCache | None":
    """The cache for one prompt version, or None when caching is off or no
    embedder is configured. Never raises: a cache is an optimisation, and an
    unconfigured embedder must not take down every chain in the process.

    Keyed on the *resolved* version, not just the name. An eval sweep that runs
    classify v1 against v2 in one process would otherwise share one cache and
    serve one version's answer for the other, silently flattening the result.
    """
    if not settings.semantic_cache_enabled:
        return None
    from app.ai.prompts import LATEST

    key = (prompt_name, LATEST[prompt_name] if version is None else version)
    if key not in _CACHES:
        from app.ai.cache import SemanticCache
        from app.ai.rag import embeddings

        try:
            _CACHES[key] = SemanticCache(
                embeddings.build_embedder(), threshold=settings.semantic_cache_threshold
            )
        except embeddings.NoEmbedderConfigured:
            return None
    return _CACHES[key]
