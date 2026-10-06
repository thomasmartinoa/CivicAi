"""Recording officer chat turns to `agent_runs` / `agent_steps`.

Here rather than in `app/ai/agents/officer_chat.py` because that module's whole
testability argument is that it persists nothing — a test drives the loop with no
database at all. The caller records, and this is the caller's half.

The tables are the ones the pipeline already writes, which is deliberate: the Phase 5
trace viewer renders `agent_steps` for a complaint run, and a chat turn is the same
shape — an ordered sequence of steps with durations, inputs and outputs. One table
means one screen rather than two.

A chat run is distinguished from a pipeline run by `complaint_id IS NULL`. Nothing
else is needed: a chat turn is not about one complaint, and forcing it to name one
would be a lie whenever the officer asked about three.

**What this stores is a transcript, and a transcript is records about real people.**
A tool result can contain a complaint description written by a member of the public,
and the officer's question can name a citizen. That is the point — an officer's
decisions should be reviewable — but it means this table inherits the retention
question that the rest of the complaint data has, and nothing in this project answers
that yet. Written down here rather than discovered later.
"""

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

AGENT_VERSION = "officer_chat.v1"
"""Recorded in `graph_version`, so a trace viewer can tell which agent produced a
run and an old transcript stays interpretable after the prompt changes."""

SUMMARY_LIMIT = 2000
"""Tool results are truncated before storage. A `find_complaints` result can carry
25 rows of description, and storing every one in full would grow this table faster
than the complaints it describes. Truncation is marked, so a reader knows the record
is partial rather than assuming the tool returned little."""


@dataclass
class RecordedTurn:
    run_id: str
    steps: int


def _summarise(value) -> str:
    """A compact, length-bounded string for a step summary."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= SUMMARY_LIMIT:
        return text
    return f"{text[:SUMMARY_LIMIT]}… [truncated from {len(text)} characters]"


def record_chat_turn(
    session: Session,
    *,
    officer_id: str,
    question: str,
    answer: str,
    tool_calls: list,
    duration_ms: int,
    error: str | None = None,
    hit_step_limit: bool = False,
) -> RecordedTurn:
    """Write one chat turn as a run plus one step per tool call.

    `started_at` is derived from `duration_ms` rather than left to the column
    default, which fires at INSERT — the same bug that made pipeline runs record a
    `finished_at` before their `started_at`.

    A failed turn is recorded too. A transcript that contains only the turns that
    worked is not an audit trail.
    """
    from datetime import timedelta
    from uuid import uuid4

    from app.db.base import utcnow
    from app.db.models.ai import AgentRun, AgentStep

    finished = utcnow()
    status = "failed" if error else "completed"
    run = AgentRun(
        complaint_id=None,
        thread_id=f"chat:{officer_id}:{uuid4().hex[:12]}",
        status=status,
        graph_version=AGENT_VERSION,
        started_at=finished - timedelta(milliseconds=max(0, duration_ms)),
        finished_at=finished,
        duration_ms=duration_ms,
        error=error,
    )
    session.add(run)
    session.flush()

    # Step 0 is the question and the answer, so a reader sees what was asked without
    # reconstructing it from tool arguments.
    session.add(AgentStep(
        run_id=run.id, seq=0, node="question",
        status="step_limit" if hit_step_limit else status,
        duration_ms=duration_ms,
        input_summary=_summarise(question),
        output_summary=_summarise(answer),
    ))
    for index, call in enumerate(tool_calls, start=1):
        session.add(AgentStep(
            run_id=run.id, seq=index, node=call.name, status="completed",
            input_summary=_summarise(call.args),
            output_summary=_summarise(call.result),
        ))

    session.commit()
    return RecordedTurn(run_id=run.id, steps=1 + len(tool_calls))
