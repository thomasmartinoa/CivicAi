"""A near-duplicate prompt returns the stored completion without a model call.

The fake embedder is content-hashed, so only identical text scores 1.0 and
anything else is uncorrelated. That is enough to test the mechanism; the
threshold's behaviour on real paraphrases is a Phase 3 eval question."""

from langchain_core.runnables import RunnableLambda

from app.ai.cache import SemanticCache, cache_key, with_semantic_cache
from app.ai.rag.embeddings import FakeEmbedder


def test_a_miss_then_a_hit():
    cache = SemanticCache(FakeEmbedder())
    assert cache.get("pothole on main road") is None
    cache.put("pothole on main road", {"category": "ROADS"})
    assert cache.get("pothole on main road") == {"category": "ROADS"}
    assert (cache.hits, cache.misses) == (1, 1)


def test_unrelated_text_does_not_hit():
    cache = SemanticCache(FakeEmbedder())
    cache.put("pothole on main road", "a")
    assert cache.get("streetlight is dark") is None


def test_the_threshold_is_respected():
    cache = SemanticCache(FakeEmbedder(), threshold=1.01)
    cache.put("x", "a")
    assert cache.get("x") is None, "even an identical prompt cannot reach a threshold above 1"


def test_the_cache_is_bounded():
    cache = SemanticCache(FakeEmbedder(), max_entries=2)
    for i in range(3):
        cache.put(f"prompt {i}", i)
    assert len(cache) == 2
    assert cache.get("prompt 0") is None, "the oldest entry is evicted"
    assert cache.get("prompt 2") == 2


def test_the_wrapped_chain_is_called_once_for_identical_input():
    calls = []
    chain = RunnableLambda(lambda payload: calls.append(payload) or {"answer": payload["description"].upper()})
    cached = with_semantic_cache(chain, SemanticCache(FakeEmbedder()), key=cache_key)
    payload = {"description": "pothole", "media_context": ""}
    assert cached.invoke(payload) == {"answer": "POTHOLE"}
    assert cached.invoke(payload) == {"answer": "POTHOLE"}
    assert len(calls) == 1


def test_the_key_is_deterministic_regardless_of_dict_order():
    assert cache_key({"a": 1, "b": "x"}) == cache_key({"b": "x", "a": 1})


def test_build_structured_wraps_with_a_cache_when_given_one(monkeypatch):
    """No network: the model is a stub. We only check the cache is consulted."""
    from app.ai import llm
    from app.ai.schemas import ValidationResult

    class StubModel:
        def with_structured_output(self, schema):
            return RunnableLambda(lambda _: ValidationResult(is_valid=True, rejection_reason=None))
    monkeypatch.setattr(llm, "build_chat_model", lambda task: StubModel())

    cache = SemanticCache(FakeEmbedder())
    chain = llm.build_structured(llm.Task.VALIDATE, ValidationResult, "validate", cache=cache)
    chain.invoke({"description": "a pothole"})
    chain.invoke({"description": "a pothole"})
    assert cache.hits == 1


def test_no_cache_when_caching_is_switched_off(monkeypatch):
    from app.ai import llm
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_cache_enabled", False)
    assert llm.cache_for("validate") is None


def test_no_cache_when_no_embedder_is_configured(monkeypatch):
    """A cache is an optimisation: an unconfigured embedder disables it rather
    than taking down every chain in the process."""
    from app.ai import llm
    from app.ai.rag import embeddings
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_cache_enabled", True)
    monkeypatch.setattr(llm, "_CACHES", {})
    def no_embedder():
        raise embeddings.NoEmbedderConfigured("no key")
    monkeypatch.setattr(embeddings, "build_embedder", no_embedder)
    assert llm.cache_for("validate") is None
