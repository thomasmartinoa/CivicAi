"""What a node is allowed to reach for, and how it gets there.

Nodes receive dependencies through `config["configurable"]` rather than by
importing them. Two reasons, both load-bearing:

- A node that constructs its own model cannot be unit-tested. LangChain's fake
  chat models raise NotImplementedError on with_structured_output, so tests
  inject an already-bound runnable instead.
- A node that imports a session factory cannot be run against a throwaway
  database without monkeypatching module globals.
"""

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any

from langchain_core.runnables import Runnable, RunnableConfig

CONFIG_KEY = "civicai_deps"


@dataclass(frozen=True)
class GraphDeps:
    """Everything the graph needs from the outside world.

    Every field defaults to None so a test can supply only what its node uses.
    A node asking for a dependency that was not supplied gets a ValueError
    naming the field, rather than an AttributeError on None.
    """

    validate_chain: Runnable | None = None
    classify_chain: Runnable | None = None
    risk_chain: Runnable | None = None
    vision_chain: Runnable | None = None
    work_order_chain: Runnable | None = None
    investigate_chain: Runnable | None = None
    policy_retriever: Any | None = None
    """Anything with .search(query, *, k, fetch_k, filters) -> list[Hit]. The
    real one is a HybridRetriever over the policy corpus; tests pass a stub."""
    cases_retriever: Any | None = None
    """Same shape, over resolved complaints. Optional: absent until the first
    case record is ingested."""
    session_factory: Callable | None = None
    """Must return a session this call may close. It is closed on every path,
    including on error, which expunges its identity map — so a caller holding
    ORM objects across the call to run_complaint must re-query them afterwards
    rather than reuse the instances it passed in."""
    geocode: Callable | None = None
    notify: Callable | None = None

    def require(self, name: str):
        """Fetch a dependency or explain precisely what is missing."""
        value = getattr(self, name, None)
        if value is None:
            available = sorted(f.name for f in fields(self) if getattr(self, f.name) is not None)
            raise ValueError(
                f"GraphDeps.{name} was not provided; supplied: {available or 'nothing'}"
            )
        return value


def to_configurable(deps: GraphDeps, thread_id: str) -> RunnableConfig:
    """Build the config a node expects. `thread_id` keys the checkpoint."""
    return {"configurable": {"thread_id": thread_id, CONFIG_KEY: deps}}


def deps_from_config(config: RunnableConfig) -> GraphDeps:
    try:
        return config["configurable"][CONFIG_KEY]
    except (KeyError, TypeError):
        raise KeyError(
            f"config['configurable'][{CONFIG_KEY!r}] is missing; "
            "build the config with app.ai.graph.deps.to_configurable()"
        ) from None
