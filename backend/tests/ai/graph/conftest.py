"""Fakes for node tests.

Nodes receive already-bound runnables, never raw models, because LangChain's
fake chat models raise NotImplementedError on with_structured_output. A stub
here is just a RunnableLambda returning a fixture.
"""

import pytest
from langchain_core.runnables import RunnableLambda

from app.ai.graph.deps import GraphDeps, to_configurable
from app.ai.graph.state import initial_state


def returns(value):
    """A stub chain that ignores its input and returns `value`."""
    return RunnableLambda(lambda _: value)


def raises(exc):
    def _boom(_):
        raise exc
    return RunnableLambda(_boom)


@pytest.fixture
def make_config():
    def _make(**overrides):
        deps = GraphDeps(**overrides)
        return to_configurable(deps, thread_id="test-thread")
    return _make


@pytest.fixture
def base_state():
    return initial_state(
        complaint_id="c-1",
        tracking_id="CIV-TEST0001",
        raw_description="There is a large pothole on the main road near the school",
    )
