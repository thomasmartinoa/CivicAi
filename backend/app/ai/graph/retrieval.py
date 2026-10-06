"""The seam between the graph and the RAG stack.

Nodes call `retrieve()` and get back RetrievedChunk objects ready to go into
state["evidence"], plus `format_evidence()` to turn them into the numbered
block a prompt cites by [n].

Retrieval is a soft dependency. A missing index, a mismatched embedder or a
dead retriever returns an empty result with an error string; the node records
the error and continues. The SLA window, the department and the tracking id
never depend on the index being present.
"""

import logging
from dataclasses import dataclass, field

from app.ai.schemas import RetrievedChunk

logger = logging.getLogger(__name__)

# FAISS cannot filter, so HybridRetriever fetches this many candidates and
# filters in Python. At 88 chunks the whole index is fetched; at a few thousand
# it is still cheap. Narrow filters (one category's SOP) need this wide a net.
DEFAULT_FETCH_K = 200


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    error: str | None = None


def retrieve(retriever, query: str, *, node: str, k: int = 4, filters: dict | None = None) -> RetrievalResult:
    """Search and convert hits; never raise."""
    if retriever is None:
        return RetrievalResult(error=f"{node}: retrieval unavailable: no retriever configured")
    try:
        hits = retriever.search(query, k=k, fetch_k=DEFAULT_FETCH_K, filters=filters)
    except Exception as exc:
        logger.warning("%s: retrieval failed", node, exc_info=True)
        return RetrievalResult(error=f"{node}: retrieval unavailable: {exc}")
    chunks = [
        RetrievedChunk(
            node=node,
            source=hit.chunk.source,
            chunk_id=hit.chunk.chunk_id,
            score=hit.score,
            snippet=hit.chunk.text,
            headers=list(hit.chunk.metadata.get("headers", [])),
        )
        for hit in hits
    ]
    return RetrievalResult(chunks=chunks)


def format_evidence(chunks: list[RetrievedChunk]) -> str:
    """Numbered evidence block. Prompts tell the model to cite [n]."""
    if not chunks:
        return "No supporting documents were retrieved."
    return "\n\n".join(f"[{i}] {c.citation}\n{c.snippet}" for i, c in enumerate(chunks, start=1))
