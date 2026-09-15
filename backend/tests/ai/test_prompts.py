import pytest
from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts import LATEST, PROMPT_REGISTRY, get_prompt


def test_every_expected_prompt_is_registered():
    assert set(LATEST) == {"validate", "classify", "assess_risk", "vision", "work_order"}


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


def test_empty_version_raises_instead_of_silently_defaulting():
    """`version or LATEST[name]` would treat "" as falsy and default silently.
    An explicit empty string is a caller mistake and must raise."""
    with pytest.raises(KeyError):
        get_prompt("classify", "")


def test_every_latest_version_is_actually_registered():
    """LATEST and PROMPT_REGISTRY are independent literals; nothing else ties them."""
    for name, version in LATEST.items():
        assert (name, version) in PROMPT_REGISTRY, f"LATEST[{name!r}]={version!r} is not registered"


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


def test_vision_prompt_carries_an_image_block_not_a_plain_string():
    """A plain-string human turn cannot carry image data to Gemini; the human
    turn must render as a list of content blocks including an image block."""
    tiny_png_data_url = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0l"
        "EQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    rendered = get_prompt("vision").format_messages(
        image_url=tiny_png_data_url,
        image_context="Additional context: reported near a school.",
    )
    human_messages = [m for m in rendered if m.type == "human"]
    assert human_messages, "expected a human message"
    content = human_messages[0].content
    assert isinstance(content, list), "human turn must be a list of content blocks, not a plain string"
    image_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "image_url"]
    assert image_blocks, f"expected an image_url block, got: {content}"
    assert image_blocks[0]["image_url"]["url"] == tiny_png_data_url


def test_the_work_order_prompt_receives_evidence_and_cites_it():
    from app.ai.prompts import get_prompt

    prompt = get_prompt("work_order")
    assert set(prompt.input_variables) == {"category", "risk_level", "description", "evidence"}
    rendered = prompt.format(category="ROADS", risk_level="high", description="x", evidence="[1] rate_card.md\n₹450")
    assert "[1] rate_card.md" in rendered
    assert "<report>" in rendered
    assert "only" in rendered.lower() and "rate card" in rendered.lower()
