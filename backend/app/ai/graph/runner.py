"""The only entry point into the graph.

Owns the checkpointer, injects dependencies, and is the single place that
writes to the database — nodes stay pure so they can be tested against fakes.

`app/api/` may import this module and nothing else under `app/ai/graph/`;
`tests/test_import_rules.py` enforces that.
"""

import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from app.ai.graph.build import GRAPH_VERSION, compile_graph
from app.ai.graph.deps import GraphDeps, to_configurable
from app.ai.graph.state import ComplaintState, build_serializer, initial_state
from app.ai.schemas import Coords, MediaRef
from app.db.base import utcnow

CHECKPOINT_DB = str(Path(__file__).resolve().parents[3] / "checkpoints.db")


def build_deps(session_factory: Callable) -> GraphDeps:
    """Wire the real chains. Tests pass their own GraphDeps instead."""
    from app.ai.llm import Task, build_structured
    from app.ai.schemas import ClassificationResult, RiskAssessment, ValidationResult, VisionObservation
    from app.services.geocoding import reverse_geocode
    from app.services.notify import notify_citizen

    return GraphDeps(
        validate_chain=build_structured(Task.VALIDATE, ValidationResult, "validate"),
        classify_chain=build_structured(Task.CLASSIFY, ClassificationResult, "classify"),
        risk_chain=build_structured(Task.ASSESS_RISK, RiskAssessment, "assess_risk"),
        vision_chain=_vision_chain(),
        session_factory=session_factory,
        geocode=reverse_geocode,
        notify=notify_citizen,
    )


def _vision_chain():
    """Adapt the media node's {"file_path"} contract to the vision prompt.

    The prompt takes `image_url` and `image_context`; the node deliberately knows
    nothing about loading files, so the bridge lives here. Reading bytes in the
    node would make it untestable without a filesystem.
    """
    import base64
    import mimetypes
    from pathlib import Path

    from langchain_core.runnables import RunnableLambda

    from app.ai.llm import Task, build_structured
    from app.ai.schemas import VisionObservation
    from app.config import settings

    def to_prompt_vars(payload: dict) -> dict:
        path = Path(settings.upload_dir).parent / payload["file_path"]
        mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "image_url": f"data:{mime};base64,{encoded}",
            "image_context": "Describe any infrastructure problem visible in this photograph.",
        }

    return RunnableLambda(to_prompt_vars) | build_structured(
        Task.VISION, VisionObservation, "vision"
    )


def _state_for(complaint) -> ComplaintState:
    coords = None
    if complaint.latitude is not None and complaint.longitude is not None:
        coords = Coords(latitude=complaint.latitude, longitude=complaint.longitude)
    return initial_state(
        complaint_id=complaint.id,
        tracking_id=complaint.tracking_id,
        tenant_id=complaint.tenant_id,
        raw_description=complaint.description,
        media=[
            MediaRef(file_path=m.file_path, media_type=m.media_type,
                     original_filename=m.original_filename)
            for m in (complaint.media or [])
        ],
        coords=coords,
    )


def _status_for(state: ComplaintState) -> str:
    """Outcome first, errors last.

    A run that finished with a soft error — geocoding timed out, say — is still
    assigned. Only a run that produced nothing is 'failed'. And a rejection is
    never 'failed': v1 conflated the two and lost both.
    """
    if state["terminal_reason"]:
        return "rejected"
    if state["work_order"]:
        return "assigned"
    if state["errors"]:
        return "failed"
    return "processed"


def persist_result(state: ComplaintState, session, *, duration_ms: int) -> None:
    from app.db.models.ai import AgentRun, AgentStep
    from app.db.models.complaint import Complaint
    from app.db.models.workflow import WorkOrder

    complaint = session.query(Complaint).filter(Complaint.id == state["complaint_id"]).one()
    status = _status_for(state)

    complaint.status = status
    complaint.terminal_reason = state["terminal_reason"]
    complaint.graph_thread_id = state["complaint_id"]
    complaint.pipeline_version = GRAPH_VERSION

    if state["classification"]:
        complaint.category = state["classification"].category.value
        complaint.subcategory = state["classification"].subcategory
        complaint.classification_confidence = state["classification"].confidence
    if state["risk"]:
        complaint.priority_score = state["risk"].priority_score
        complaint.risk_level = state["risk"].risk_level.value
    if state["location"]:
        location = state["location"]
        complaint.address = location.address or complaint.address
        complaint.ward = location.ward or complaint.ward
        complaint.block = location.block or complaint.block
        complaint.district = location.district or complaint.district
        complaint.state = location.state or complaint.state
    if state["evidence"]:
        complaint.evidence = [chunk.model_dump() for chunk in state["evidence"]]

    if state["work_order"] and status == "assigned":
        draft = state["work_order"]
        routing = state["routing"]
        session.add(WorkOrder(
            complaint_id=complaint.id,
            tenant_id=complaint.tenant_id,
            contractor_id=routing.contractor_id if routing else None,
            status="assigned" if (routing and routing.contractor_id) else "created",
            sla_hours=draft.sla_hours,
            sla_deadline=utcnow() + timedelta(hours=draft.sla_hours),
            estimated_cost=draft.estimated_cost,
            cost_basis=draft.cost_basis,
            materials=draft.materials,
            notes=draft.summary,
        ))

    run = AgentRun(
        complaint_id=complaint.id,
        thread_id=state["complaint_id"],
        status="completed" if status != "failed" else "failed",
        graph_version=GRAPH_VERSION,
        finished_at=utcnow(),
        duration_ms=duration_ms,
        error="; ".join(state["errors"]) or None,
    )
    session.add(run)
    session.flush()

    for seq, decision in enumerate(state["decision_log"]):
        session.add(AgentStep(
            run_id=run.id,
            seq=seq,
            node=decision.node,
            status="ok",
            duration_ms=decision.duration_ms,
            output_summary=decision.summary,
        ))

    session.commit()


async def run_complaint(
    complaint_id: str,
    *,
    session_factory: Callable,
    deps: GraphDeps | None = None,
    checkpointer=None,
) -> ComplaintState:
    """Run one complaint through the graph and persist what happened.

    `thread_id` is the complaint id, so re-invoking with the same id resumes
    that complaint's run rather than starting a new one.
    """
    from app.db.models.complaint import Complaint

    session = session_factory()
    complaint = session.query(Complaint).filter(Complaint.id == complaint_id).one()
    state = _state_for(complaint)
    deps = deps or build_deps(session_factory)
    config = to_configurable(deps, thread_id=complaint_id)

    started = time.monotonic()
    if checkpointer is not None:
        result = await compile_graph(checkpointer=checkpointer).ainvoke(state, config)
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB) as saver:
            # Without this, Pydantic models in state come back from the
            # checkpoint as plain dicts and every later field access fails.
            saver.serde = build_serializer()
            result = await compile_graph(checkpointer=saver).ainvoke(state, config)
    duration_ms = int((time.monotonic() - started) * 1000)

    persist_result(result, session, duration_ms=duration_ms)
    return result
