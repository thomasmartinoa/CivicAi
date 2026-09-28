import sys

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

from app.ai import llm as llm_module
from app.ai.llm import (
    SHARED_RATE_LIMITER, TASK_MODEL, NoModelConfigured, Task,
    available_providers, build_chat_model, build_structured,
)
from app.ai.schemas import ClassificationResult
from app.constants import Category


def test_every_task_has_a_model_tier():
    """A task missing from the map would silently fall back to a default."""
    assert set(TASK_MODEL) == set(Task)


def test_cheap_and_strong_tiers_are_actually_different():
    assert TASK_MODEL[Task.CLASSIFY] != TASK_MODEL[Task.NARRATE]


def test_no_providers_configured_is_a_clear_error(monkeypatch):
    """v1 silently degraded to keyword matching with no signal that it had."""
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", None)
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", False)
    assert available_providers() == []
    with pytest.raises(NoModelConfigured, match="GEMINI_API_KEY"):
        build_chat_model(Task.CLASSIFY)


def test_gemini_alone_is_reported_available(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", False)
    assert available_providers() == ["gemini"]


def test_both_providers_puts_gemini_first(monkeypatch):
    """Order matters: the first is primary, the rest are fallbacks."""
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", True)
    assert available_providers() == ["gemini", "ollama"]


def test_ollama_alone_is_usable(monkeypatch):
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", None)
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", True)
    assert available_providers() == ["ollama"]


def test_ollama_enabled_without_the_package_raises_no_model_configured(monkeypatch):
    """langchain-ollama is deliberately not in requirements.txt.
    available_providers() reports ollama as available without checking the
    package exists, so the ImportError must be caught and turned into an
    actionable NoModelConfigured rather than leaking out raw."""
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", None)
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", True)
    monkeypatch.setitem(sys.modules, "langchain_ollama", None)  # forces ImportError
    with pytest.raises(NoModelConfigured, match="langchain-ollama"):
        build_chat_model(Task.CLASSIFY)


def test_rate_limiter_is_shared_across_tasks():
    """One ceiling for the whole process, not one per model instance."""
    assert SHARED_RATE_LIMITER is llm_module.SHARED_RATE_LIMITER


class _StubModel(GenericFakeChatModel):
    def with_structured_output(self, schema, **kwargs) -> Runnable:
        return RunnableLambda(lambda _: ClassificationResult(category="ROADS", confidence=0.5))


def test_build_structured_composes_prompt_model_and_fallbacks(monkeypatch):
    """Exercises the RunnableWithFallbacks.__getattr__ proxy for with_structured_output.

    The explicit `-> Runnable` return annotation on the stub above is load-bearing:
    the proxy resolves type hints, and an unresolvable annotation makes it fail.
    """
    monkeypatch.setattr(llm_module.settings, "gemini_api_key", "x")
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", True)
    monkeypatch.setattr(
        llm_module, "_build_one",
        lambda provider, task: _StubModel(messages=iter([AIMessage(content="{}")])),
    )
    chain = build_structured(Task.CLASSIFY, ClassificationResult, "classify")
    result = chain.invoke({"description": "pothole", "media_context": ""})
    assert result.category is Category.ROADS


def test_build_structured_retries_a_failing_chain(monkeypatch):
    """RetryPolicy only fires when a node raises, and every LLM node catches its
    own exception -- so the retry has to live inside the chain."""
    attempts = {"n": 0}

    class _Flaky(GenericFakeChatModel):
        def with_structured_output(self, schema, **kwargs) -> Runnable:
            def run(_):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise RuntimeError("503 transient")
                return ClassificationResult(category="ROADS", confidence=0.9)
            return RunnableLambda(run)

    monkeypatch.setattr(llm_module.settings, "gemini_api_key", "x")
    monkeypatch.setattr(llm_module.settings, "ollama_enabled", False)
    monkeypatch.setattr(llm_module, "_build_one",
                        lambda p, t: _Flaky(messages=iter([AIMessage(content="{}")])))
    # with_retry's default backoff is real exponential-jitter sleep (tenacity's
    # nap.sleep, which calls time.sleep) -- several real seconds for 3 attempts.
    # Skip the wait; this test is about attempt count, not backoff timing.
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    chain = build_structured(Task.CLASSIFY, ClassificationResult, "classify")
    result = chain.invoke({"description": "pothole", "media_context": ""})
    assert attempts["n"] == 3
    assert result.category is Category.ROADS


def test_fake_models_cannot_do_structured_output():
    """Documents WHY the injection seam above exists, so nobody 'simplifies' it."""
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="{}")]))
    with pytest.raises(NotImplementedError):
        fake.with_structured_output(ClassificationResult)


def test_build_structured_can_be_asked_for_fewer_retries(monkeypatch):
    """An eval sweep has its own outer loop and its own fail-fast, so it does not
    want the chain's three attempts stacked on the client's three. A live sweep
    against a 503-ing provider spent over two minutes per item on retries before
    reporting a failure the harness was going to record anyway."""
    from langchain_core.runnables import RunnableLambda

    from app.ai import llm
    from app.ai.schemas import ValidationResult

    class StubModel:
        def with_structured_output(self, schema):
            return RunnableLambda(lambda _: ValidationResult(is_valid=True))

    monkeypatch.setattr(llm, "build_chat_model", lambda task: StubModel())

    once = llm.build_structured(llm.Task.VALIDATE, ValidationResult, "validate", retries=1)
    assert once.invoke({"description": "a pothole"}).is_valid is True

    with pytest.raises(ValueError, match="at least 1"):
        llm.build_structured(llm.Task.VALIDATE, ValidationResult, "validate", retries=0)


def test_retries_default_to_three_so_production_is_unchanged(monkeypatch):
    from langchain_core.runnables import RunnableLambda

    from app.ai import llm
    from app.ai.schemas import ValidationResult

    attempts = []

    class Flaky:
        def with_structured_output(self, schema):
            def fail(_):
                attempts.append(1)
                raise RuntimeError("503 UNAVAILABLE")
            return RunnableLambda(fail)

    monkeypatch.setattr(llm, "build_chat_model", lambda task: Flaky())
    chain = llm.build_structured(llm.Task.VALIDATE, ValidationResult, "validate")
    with pytest.raises(RuntimeError):
        chain.invoke({"description": "a pothole"})
    assert len(attempts) == 3, "production keeps its three attempts"

    attempts.clear()
    with pytest.raises(RuntimeError):
        llm.build_structured(llm.Task.VALIDATE, ValidationResult, "validate",
                             retries=1).invoke({"description": "a pothole"})
    assert len(attempts) == 1, "an eval asks for one"


def test_the_gemini_client_is_given_a_request_timeout(monkeypatch):
    """Found the hard way: an eval sweep sat on a single request for five minutes
    with no response and no retry — the connection had stalled, and nothing in the
    stack had a timeout. In production that hangs a complaint's background run
    forever, which is worse: the run never completes and never fails."""
    from app.ai import llm
    from app.config import settings

    captured = {}

    class FakeChat:
        model_fields = {"timeout": None}

        def __init__(self, **kwargs):
            captured.update(kwargs)

    import langchain_google_genai
    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", FakeChat)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    llm._build_one("gemini", llm.Task.CLASSIFY)
    assert captured["timeout"] == settings.llm_timeout_seconds
    assert settings.llm_timeout_seconds > 0


def test_the_timeout_is_long_enough_for_a_slow_model_but_not_forever():
    """Long enough that a genuinely slow structured-output call is not cut off,
    short enough that a stalled socket surfaces as an error the node can record."""
    from app.config import settings

    assert 20 <= settings.llm_timeout_seconds <= 180
