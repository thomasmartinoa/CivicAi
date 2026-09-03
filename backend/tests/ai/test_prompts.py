import pytest
from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts import LATEST, PROMPT_REGISTRY, get_prompt


def test_every_expected_prompt_is_registered():
    assert set(LATEST) == {"validate", "classify", "assess_risk", "vision"}


def test_get_prompt_returns_the_latest_version_by_default():
    assert isinstance(get_prompt("classify"), ChatPromptTemplate)


def test_get_prompt_can_pin_an_explicit_version():
    """Versioning is what lets the Phase 3 eval harness A/B two prompts."""
    assert get_prompt("classify", "v1") is PROMPT_REGISTRY[("classify", "v1")]


def test_unknown_prompt_name_raises_with_a_useful_message():
    with pytest.raises(KeyError, match="nonexistent"):
        get_prompt("nonexistent")


def test_unknown_version_raises_with_a_useful_message():
    with pytest.raises(KeyError, match="v99"):
        get_prompt("classify", "v99")


def test_classify_prompt_declares_the_variables_its_node_supplies():
    assert set(get_prompt("classify").input_variables) == {"description", "media_context"}


def test_validate_prompt_declares_its_variables():
    assert set(get_prompt("validate").input_variables) == {"description"}


def test_assess_risk_prompt_declares_its_variables():
    assert set(get_prompt("assess_risk").input_variables) == {
        "description", "category", "media_context"
    }


def test_classify_prompt_renders_with_untrusted_text_without_breaking():
    """Citizen text is untrusted input. Braces in it must not blow up templating."""
    rendered = get_prompt("classify").format_messages(
        description="pothole near {curly} braces and a $dollar",
        media_context="",
    )
    assert any("curly" in m.content for m in rendered)


def test_every_registered_prompt_renders_from_its_declared_variables():
    for (name, version), template in PROMPT_REGISTRY.items():
        filler = {var: "x" for var in template.input_variables}
        messages = template.format_messages(**filler)
        assert messages, f"{name}/{version} rendered nothing"
