"""Tokens, latency and cost — or an honest blank.

There are **no default cost rates in this file and there never will be.** A
per-token price invented in source is the single number most likely to be lifted
into a README and quoted at somebody. Cost appears in the report only when the
operator has written the prices they were actually quoted into a JSON file, and
that file must name its source, because a price with no provenance is a number
someone has to defend later.

Latency is wall clock, including time spent waiting on the shared rate limiter.
On the free tier that dominates: a single item measured 122s in one Task 4 probe.
The report says "wall clock" and prints `LLM_REQUESTS_PER_SECOND` beside it, so
nobody reads it as model speed. Token counts come from LangChain's usage callback
and are unaffected by the waiting.
"""

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostRates:
    source: str
    """Where these prices came from and when. Required."""
    per_million_input: float
    per_million_output: float


def load_cost_rates(path: Path | None) -> CostRates | None:
    """The operator's rates, or None. Never a default."""
    if path is None or not Path(path).exists():
        logger.info("no cost rates at %s; cost will be reported as not configured", path)
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not payload.get("source"):
        raise ValueError(
            f"{path}: a rates file must carry a 'source' naming where the prices came "
            "from and when — an unsourced price is one nobody can defend later"
        )
    return CostRates(
        source=payload["source"],
        per_million_input=float(payload["per_million_input"]),
        per_million_output=float(payload["per_million_output"]),
    )


def estimated_cost(input_tokens: int | None, output_tokens: int | None,
                   rates: CostRates | None) -> float | None:
    """Cost in the rates' currency, or None when it cannot be computed."""
    if rates is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens / 1_000_000 * rates.per_million_input
            + output_tokens / 1_000_000 * rates.per_million_output)


@contextmanager
def token_counter():
    """Count tokens across every model call made inside the block.

    Yields an object with `.input_tokens` and `.output_tokens`, both None when the
    provider reported no usage metadata — None rather than 0, so the report can
    tell "the provider did not say" from "it used nothing".
    """
    try:
        from langchain_core.callbacks import get_usage_metadata_callback
    except ImportError:  # pragma: no cover - langchain-core always provides it
        logger.warning("no usage callback available; token counts will be blank")
        yield _Counted(None, None, [])
        return

    with get_usage_metadata_callback() as callback:
        counted = _Counted(None, None, [])
        yield counted
        usage = getattr(callback, "usage_metadata", None) or {}
        inputs = [v.get("input_tokens") for v in usage.values() if isinstance(v, dict)]
        outputs = [v.get("output_tokens") for v in usage.values() if isinstance(v, dict)]
        counted.input_tokens = sum(t for t in inputs if t) or None
        counted.output_tokens = sum(t for t in outputs if t) or None
        counted.callbacks = [callback]


@dataclass
class _Counted:
    input_tokens: int | None
    output_tokens: int | None
    callbacks: list
