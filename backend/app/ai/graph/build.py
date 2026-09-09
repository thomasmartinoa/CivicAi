"""Assemble the complaint graph.

The shape IS the business process. v1's equivalent was the order of seven
`add_agent` calls in a function, with no branching available at all.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.ai.graph.edges import after_assess_risk, after_classify, after_validate
from app.ai.graph.nodes.assess_risk import assess_risk_node
from app.ai.graph.nodes.classify import classify_node
from app.ai.graph.nodes.intake import fan_out_media, intake_node
from app.ai.graph.nodes.media import analyse_media_node
from app.ai.graph.nodes.notify import notify_node
from app.ai.graph.nodes.route import route_node
from app.ai.graph.nodes.validate import validate_node
from app.ai.graph.nodes.work_order import work_order_node
from app.ai.graph.state import ComplaintState

GRAPH_VERSION = "1b.0"

# Retries cover transient provider failures. Note these compound with the
# client's own max_retries — see the comment on SHARED_RATE_LIMITER.
LLM_RETRY = RetryPolicy(max_attempts=3)


def build_graph() -> StateGraph:
    builder = StateGraph(ComplaintState)

    builder.add_node("intake", intake_node)
    builder.add_node("analyse_media", analyse_media_node, retry_policy=LLM_RETRY)
    builder.add_node("validate", validate_node, retry_policy=LLM_RETRY)
    builder.add_node("classify", classify_node, retry_policy=LLM_RETRY)
    builder.add_node("assess_risk", assess_risk_node, retry_policy=LLM_RETRY)
    builder.add_node("route", route_node)
    builder.add_node("work_order", work_order_node)
    builder.add_node("notify", notify_node)

    builder.add_edge(START, "intake")
    # Fan out one branch per uploaded file, or skip straight on when there is none.
    builder.add_conditional_edges("intake", fan_out_media, ["analyse_media", "validate"])
    builder.add_edge("analyse_media", "validate")
    builder.add_conditional_edges("validate", after_validate, ["classify", END])
    builder.add_conditional_edges("classify", after_classify, ["assess_risk", END])
    # Fail closed: work_order reads state["risk"] unconditionally, so a failed
    # assessment must not reach it.
    builder.add_conditional_edges("assess_risk", after_assess_risk, ["route", END])
    builder.add_edge("route", "work_order")
    builder.add_edge("work_order", "notify")
    builder.add_edge("notify", END)

    return builder


def compile_graph(checkpointer=None):
    return build_graph().compile(checkpointer=checkpointer)
