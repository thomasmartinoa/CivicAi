"""Re-classify an unsure complaint with the taxonomy in hand.

The classifier's prompt carries four lines of guidance on confusable pairs.
The taxonomy document carries all twelve categories with their hand-offs, and
every SOP's Scope section names two edge cases it gives away. When the first
pass is unsure, this node retrieves that material and asks a stronger model to
decide again, citing the rule it applied.

It is a loop, bounded by MAX_INVESTIGATE_TURNS in edges.py. Each turn widens
the taxonomy search so the model sees more of the document; a failed turn
still counts, so the loop always terminates.
"""

from langchain_core.runnables import RunnableConfig

from app.ai.graph.deps import deps_from_config
from app.ai.graph.retrieval import format_evidence, retrieve
from app.ai.graph.state import ComplaintState
from app.ai.schemas import NodeDecision


def _media_context(state: ComplaintState) -> str:
    return "\n".join(
        f"[{insight.media_type}] {insight.text}" for insight in state["media_insights"]
    )


def investigate_node(state: ComplaintState, config: RunnableConfig) -> dict:
    deps = deps_from_config(config)
    previous = state["classification"]
    turn = state["investigate_turns"] + 1

    taxonomy = retrieve(deps.policy_retriever, state["description"],
                        node="investigate", k=2 + turn, filters={"doc_type": "taxonomy"})
    scopes = retrieve(deps.policy_retriever, f"scope and hand-offs: {state['description']}",
                      node="investigate", k=2, filters={"doc_type": "sop"})
    evidence = taxonomy.chunks + scopes.chunks
    errors = [taxonomy.error] if taxonomy.error else []

    try:
        chain = deps.require("investigate_chain")
        result = chain.invoke({
            "description": state["description"],
            "media_context": _media_context(state),
            "previous_category": previous.category.value,
            "previous_confidence": previous.confidence,
            "evidence": format_evidence(evidence),
        })
    except Exception as exc:
        return {
            "classification": previous,
            "investigate_turns": turn,
            "evidence": evidence,
            "errors": errors + [f"investigate: {exc}"],
            "decision_log": [NodeDecision(node="investigate", summary=f"turn {turn} failed: {exc}")],
        }

    return {
        "classification": result,
        "investigate_turns": turn,
        "evidence": evidence,
        "errors": errors,
        "decision_log": [NodeDecision(
            node="investigate",
            summary=f"turn {turn}: {previous.category.value} {previous.confidence:.2f} -> "
                    f"{result.category.value} {result.confidence:.2f}",
        )],
    }
