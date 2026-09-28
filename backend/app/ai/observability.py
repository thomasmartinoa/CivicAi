"""Tracing, and the blind spots in it.

LangGraph and LangChain trace themselves once LangSmith is configured. FAISS
retrieval and the semantic cache are plain Python, so they appear in a trace as
unexplained gaps between model calls — which is exactly where this project's
interesting behaviour lives. `@traced` closes those gaps.

Two rules:

- **Invisible when off.** `@traced` returns the function unchanged unless tracing
  is both switched on and configured with a key, and `langsmith` is never imported
  at module scope: importing it eagerly would slow every process that never traces,
  including the test suite. A missing or broken langsmith degrades to no tracing
  rather than taking the pipeline down.
- **No citizen data leaves the building.** `run_metadata` carries the internal ids
  and the AI's own outputs, and deliberately omits the description, the address and
  every contact field. It also omits the **tracking id**, which is easy to miss:
  that string is the only credential for reading a complaint and is generated to be
  unguessable (see `api/complaints.py`), so putting it in a third party's logs would
  be handing out access.
"""

import logging
from collections.abc import Callable

from app.config import settings

logger = logging.getLogger(__name__)

# Wrapped functions, by name, so the langsmith import and the wrapping happen at
# most once per traced function rather than on every call.
_CACHE: dict[str, Callable] = {}


def tracing_enabled() -> bool:
    """On only when asked for *and* configured.

    A flag with no key would make every call attempt a trace and fail, turning an
    observability feature into a per-request error.
    """
    return bool(settings.langsmith_tracing and settings.langsmith_api_key)


def _load_traceable():
    """langsmith's decorator factory, or None when it cannot be used."""
    try:
        from langsmith import traceable  # noqa: PLC0415 - deliberately lazy
    except Exception:  # pragma: no cover - only when the extra is absent
        logger.warning("tracing is on but langsmith could not be imported; continuing untraced")
        return None
    return traceable


def traced(name: str, *, run_type: str = "chain") -> Callable:
    """Record this function in the trace when tracing is on; otherwise do nothing.

    The decision is made per call rather than at import time, so switching the
    setting takes effect without a restart — and so a test can exercise both paths.
    """

    def decorate(function: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            if not tracing_enabled():
                return function(*args, **kwargs)

            wrapped = _CACHE.get(name)
            if wrapped is None:
                factory = _load_traceable()
                if factory is None:
                    # Cache the plain function so a broken import is not retried
                    # on every single retrieval.
                    _CACHE[name] = function
                    return function(*args, **kwargs)
                wrapped = _CACHE[name] = factory(name=name, run_type=run_type)(function)
            return wrapped(*args, **kwargs)

        wrapper.__name__ = getattr(function, "__name__", name)
        wrapper.__doc__ = function.__doc__
        wrapper.__wrapped__ = function
        return wrapper

    return decorate


def run_metadata(complaint) -> dict:
    """What a trace may say about a complaint.

    Internal ids and the AI's own conclusions — enough to filter LangSmith by
    category or pipeline version when hunting a regression. Nothing a person wrote
    and nothing that identifies them, because this is sent to a third party and a
    trace backend is not a place to store a citizen's address.
    """
    return {
        "complaint_id": complaint.id,
        "tenant_id": complaint.tenant_id,
        "category": complaint.category,
        "risk_level": complaint.risk_level,
        "priority_score": complaint.priority_score,
        "pipeline_version": complaint.pipeline_version,
    }
