import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.ai import llm as llm_module
from app.ai.llm import (
    SHARED_RATE_LIMITER, TASK_MODEL, NoModelConfigured, Task,
    available_providers, build_chat_model, build_structured,
)
from app.ai.schemas import ClassificationResult


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


def test_rate_limiter_is_shared_across_tasks():
    """One ceiling for the whole process, not one per model instance."""
    assert SHARED_RATE_LIMITER is llm_module.SHARED_RATE_LIMITER


def test_build_structured_accepts_an_injected_model(monkeypatch):
    """The seam that makes nodes testable.

    LangChain's fake chat models raise NotImplementedError on
    with_structured_output, so tests inject an already-structured runnable
    instead of a raw model.
    """
    stub = RunnableLambda(
        lambda _: ClassificationResult(category="ROADS", confidence=0.88)
    )
    result = stub.invoke({"description": "pothole", "media_context": ""})
    assert result.category == "ROADS"


def test_fake_models_cannot_do_structured_output():
    """Documents WHY the injection seam above exists, so nobody 'simplifies' it."""
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="{}")]))
    with pytest.raises(NotImplementedError):
        fake.with_structured_output(ClassificationResult)
