"""The officer chat endpoint: a ReAct agent over Server-Sent Events.

SSE rather than WebSocket, and hand-framed rather than via `sse-starlette`. The
traffic is one-directional — the officer sends a question over HTTP and watches
events come back — so a WebSocket's duplex channel would be machinery for nothing,
and SSE reconnects by itself. Hand-framing avoids a dependency for six lines of
string formatting.

**The generator does not use the request's session.** A `StreamingResponse` body runs
*after* the route function returns, by which point FastAPI has closed anything
`Depends(get_db)` yielded. The tools therefore get `_session_factory()`, a
module-level accessor a test can replace — the same shape as `_email_draft_chain` in
`admin.py`, and for the same reason: it is the seam that lets this be tested without
a provider or a second database.

**Errors split by when they happen.** Anything knowable before the first byte — no
token, wrong role, an empty question — is an ordinary HTTP status. Anything after is
an `error` event, because the response is already 200 and the only channel left is the
stream itself. A client that sees the connection close without a terminal event
should treat that as a failure.
"""

import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentOfficer
from app.db.session import get_db
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Events the stream can emit. `done` always comes last, including after `error`, so a
# client has exactly one signal that the turn is over.
EVENTS = ("tool_call", "tool_result", "answer", "error", "done")


def _session_factory():
    """The factory the tools use. Replaced in tests."""
    from app.db.session import SessionLocal

    return SessionLocal


def _chat_model():
    """The model for the agent. Replaced in tests."""
    from app.ai.llm import Task, build_chat_model

    return build_chat_model(Task.OFFICER_CHAT)


def _policy_retriever():
    from app.ai.graph.runner import _POLICY_RETRIEVER

    return _POLICY_RETRIEVER


def _record(**kwargs) -> None:
    """Persist the turn, and never let a logging failure break the stream.

    The officer has their answer by the time this runs. A database error here is
    worth a stack trace in the log and nothing else — turning it into a failed
    response would mean losing an answer that already arrived because recording it
    went wrong.
    """
    from app.services.chat_log import record_chat_turn

    session = _session_factory()()
    try:
        record_chat_turn(session, **kwargs)
    except Exception:
        logger.exception("could not record an officer chat turn")
        session.rollback()
    finally:
        session.close()


def _frame(event: str, payload: dict) -> str:
    """One SSE frame.

    `json.dumps` with no newlines in the output matters: a literal newline inside a
    `data:` line would end the frame early and the client would parse half an event.
    """
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.post("/chat")
async def officer_chat(
    payload: ChatRequest,
    officer: CurrentOfficer,
    _db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    """Ask the officer assistant a question. Streams Server-Sent Events.

    Events, in the order they can occur:

    - `tool_call`  — `{name, args}`, emitted *before* the tool runs, so the screen can
      say "searching the roads SOP…" rather than showing a spinner for four seconds.
      This is what the spec means by surfacing tool calls as they happen.
    - `tool_result` — `{name, result}`.
    - `answer` — `{text, hit_step_limit?}`.
    - `error` — `{message}`, terminal.
    - `done` — `{}`, always last.

    Every tool is bound to this officer's tenant in a closure the model cannot reach,
    so no question — however phrased, and whatever a complaint description in the
    results tells the model to do — can reach another department's data.
    """
    from app.ai.agents.officer_chat import build_officer_agent, stream_officer_chat
    from app.ai.tools.officer import build_officer_tools

    # Built before the response starts, so a configuration failure is a 500 with a
    # traceback in the log rather than a half-opened stream.
    tools = build_officer_tools(
        _session_factory(),
        tenant_id=officer.tenant_id,
        policy_retriever=_policy_retriever(),
    )
    agent = build_officer_agent(_chat_model(), tools)
    history = [turn.model_dump() for turn in payload.history]
    question = payload.question
    officer_id = officer.id

    async def events():
        # Accumulated as the events go out, then written once at the end. Writing a
        # row per event would put a database round trip between the officer and each
        # token of the answer.
        from app.ai.agents.officer_chat import ToolCall

        started = time.monotonic()
        calls: list[ToolCall] = []
        answer = ""
        failure: str | None = None
        hit_limit = False

        try:
            async for event, data in stream_officer_chat(question, agent=agent,
                                                         history=history):
                if event == "tool_call":
                    calls.append(ToolCall(name=data["name"], args=data["args"]))
                elif event == "tool_result":
                    # Matched by name against the most recent call of that name:
                    # the stream has already flattened the tool_call_ids away, and a
                    # transcript does not need to disambiguate two identical calls.
                    for call in reversed(calls):
                        if call.name == data["name"] and call.result is None:
                            call.result = data["result"]
                            break
                elif event == "answer":
                    answer = data.get("text", "")
                    hit_limit = bool(data.get("hit_step_limit"))
                elif event == "error":
                    failure = data.get("message")
                yield _frame(event, data)
        except Exception as exc:
            # stream_officer_chat traps provider errors itself; this is the backstop
            # for anything it does not, and it must still frame an event rather than
            # drop a 200 response with no explanation.
            logger.exception("the officer chat stream failed for officer %s", officer_id)
            failure = f"{type(exc).__name__}: {exc}"
            yield _frame("error", {"message": "The assistant is unavailable."})
        finally:
            _record(
                officer_id=officer_id, question=question, answer=answer,
                tool_calls=calls, duration_ms=int((time.monotonic() - started) * 1000),
                error=failure, hit_step_limit=hit_limit,
            )
            yield _frame("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Without this an nginx in front buffers the whole response and the
            # as-they-happen tool events arrive all at once at the end, which is the
            # one thing this endpoint exists to avoid.
            "X-Accel-Buffering": "no",
        },
    )
