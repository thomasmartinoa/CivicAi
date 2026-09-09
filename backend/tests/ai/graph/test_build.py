import pytest
from langgraph.graph import END, START

from app.ai.graph.build import GRAPH_VERSION, build_graph, compile_graph


def test_the_graph_compiles():
    assert compile_graph() is not None


def test_every_node_is_reachable_from_start():
    graph = compile_graph().get_graph()
    reachable, frontier = {START}, [START]
    while frontier:
        current = frontier.pop()
        for edge in graph.edges:
            if edge.source == current and edge.target not in reachable:
                reachable.add(edge.target)
                frontier.append(edge.target)
    unreachable = {n for n in graph.nodes if n not in reachable} - {START, END}
    assert not unreachable, f"unreachable nodes: {sorted(unreachable)}"


def test_every_node_can_reach_end():
    """A node with no path to END hangs the run."""
    graph = compile_graph().get_graph()
    can_finish, changed = {END}, True
    while changed:
        changed = False
        for edge in graph.edges:
            if edge.target in can_finish and edge.source not in can_finish:
                can_finish.add(edge.source)
                changed = True
    stuck = {n for n in graph.nodes if n not in can_finish} - {END}
    assert not stuck, f"nodes with no path to END: {sorted(stuck)}"


def test_the_expected_nodes_are_present():
    nodes = set(compile_graph().get_graph().nodes)
    assert {"intake", "analyse_media", "validate", "classify",
            "assess_risk", "route", "work_order", "notify"} <= nodes


def test_graph_version_is_recorded():
    """Stamped onto every AgentRun so a trace can be tied back to a graph shape."""
    assert GRAPH_VERSION


def test_llm_nodes_carry_a_retry_policy():
    """A transient 503 killed a v1 complaint outright."""
    builder = build_graph()
    for name in ("validate", "classify", "assess_risk", "analyse_media"):
        assert builder.nodes[name].retry_policy, f"{name} has no retry policy"


def test_non_model_nodes_carry_no_retry_policy():
    """RetryPolicy retries *within* one node execution, before the node's update
    reaches state — so notify's decision_log idempotency guard has not been
    written yet on the retry. A retry policy here would double-send the citizen
    notification and the guard could not catch it."""
    builder = build_graph()
    for name in ("intake", "route", "work_order", "notify"):
        assert not builder.nodes[name].retry_policy, f"{name} must not retry"
