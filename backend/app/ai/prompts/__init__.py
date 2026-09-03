"""Prompt registry.

Keyed by (name, version) so the Phase 3 eval harness can run the same complaint
through two prompt versions and report which classified better.
"""

from langchain_core.prompts import ChatPromptTemplate

from app.ai.prompts.templates import (
    ASSESS_RISK_V1, CLASSIFY_V1, CLASSIFY_V2, VALIDATE_V1, VISION_V1,
)

PROMPT_REGISTRY: dict[tuple[str, str], ChatPromptTemplate] = {
    ("validate", "v1"): VALIDATE_V1,
    ("classify", "v1"): CLASSIFY_V1,
    ("classify", "v2"): CLASSIFY_V2,
    ("assess_risk", "v1"): ASSESS_RISK_V1,
    ("vision", "v1"): VISION_V1,
}

# The version each node uses unless told otherwise.
LATEST: dict[str, str] = {
    "validate": "v1",
    "classify": "v2",
    "assess_risk": "v1",
    "vision": "v1",
}


def get_prompt(name: str, version: str | None = None) -> ChatPromptTemplate:
    """Fetch a registered prompt, defaulting to the version in LATEST."""
    if name not in LATEST:
        raise KeyError(f"unknown prompt {name!r}; registered: {sorted(LATEST)}")
    resolved = version or LATEST[name]
    try:
        return PROMPT_REGISTRY[(name, resolved)]
    except KeyError:
        available = sorted(v for (n, v) in PROMPT_REGISTRY if n == name)
        raise KeyError(
            f"unknown version {resolved!r} for prompt {name!r}; available: {available}"
        ) from None


__all__ = ["PROMPT_REGISTRY", "LATEST", "get_prompt"]
