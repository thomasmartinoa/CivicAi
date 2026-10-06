"""Recording officer chat turns.

The transcript is the audit trail, so the tests are mostly about what must still be
there when something went wrong.
"""

import pytest

from app.ai.agents.officer_chat import ToolCall
from app.db.models.ai import AgentRun, AgentStep
from app.services.chat_log import AGENT_VERSION, SUMMARY_LIMIT, record_chat_turn


def _steps(db_session, run_id):
    return (db_session.query(AgentStep).filter_by(run_id=run_id)
            .order_by(AgentStep.seq).all())


def test_a_turn_is_a_run_plus_a_step_per_tool_call(db_session):
    recorded = record_chat_turn(
        db_session, officer_id="o1", question="what breaches tonight?",
        answer="Two orders.", duration_ms=1200,
        tool_calls=[ToolCall(name="work_orders_at_risk", args={}, result="2 rows"),
                    ToolCall(name="get_complaint", args={"tracking_id": "CIV-1"},
                             result="a drain")],
    )
    assert recorded.steps == 3

    steps = _steps(db_session, recorded.run_id)
    assert [s.node for s in steps] == ["question", "work_orders_at_risk", "get_complaint"]
    assert steps[0].input_summary == "what breaches tonight?"
    assert steps[0].output_summary == "Two orders."
    assert steps[2].input_summary == '{"tracking_id": "CIV-1"}'


def test_a_chat_run_names_no_complaint(db_session):
    """A chat turn is not about one complaint, and forcing it to name one would be a
    lie whenever the officer asked about three. complaint_id IS NULL is what
    distinguishes a chat run from a pipeline run."""
    recorded = record_chat_turn(db_session, officer_id="o1", question="q", answer="a",
                                duration_ms=10, tool_calls=[])
    run = db_session.query(AgentRun).filter_by(id=recorded.run_id).one()
    assert run.complaint_id is None
    assert run.graph_version == AGENT_VERSION


def test_the_run_interval_is_sane(db_session):
    """started_at is derived from the duration rather than left to the column
    default, which fires at INSERT — the bug that made pipeline runs record a
    finished_at before their started_at."""
    recorded = record_chat_turn(db_session, officer_id="o1", question="q", answer="a",
                                duration_ms=2500, tool_calls=[])
    run = db_session.query(AgentRun).filter_by(id=recorded.run_id).one()
    assert run.started_at <= run.finished_at
    measured = (run.finished_at - run.started_at).total_seconds() * 1000
    assert abs(measured - 2500) < 2


def test_a_failed_turn_is_still_recorded(db_session):
    """A transcript containing only the turns that worked is not an audit trail."""
    recorded = record_chat_turn(
        db_session, officer_id="o1", question="what breaches?", answer="",
        duration_ms=500, tool_calls=[], error="503 UNAVAILABLE",
    )
    run = db_session.query(AgentRun).filter_by(id=recorded.run_id).one()
    assert run.status == "failed"
    assert run.error == "503 UNAVAILABLE"
    assert _steps(db_session, recorded.run_id)[0].input_summary == "what breaches?"


def test_a_step_limit_overrun_is_distinguishable_from_a_clean_answer(db_session):
    """Otherwise a surrender reads as a conclusion when someone reviews it later."""
    recorded = record_chat_turn(db_session, officer_id="o1", question="everything",
                                answer="I could not answer that.", duration_ms=30000,
                                tool_calls=[], hit_step_limit=True)
    assert _steps(db_session, recorded.run_id)[0].status == "step_limit"


def test_a_long_tool_result_is_truncated_and_says_so(db_session):
    """A find_complaints result can carry 25 descriptions. Storing every one in full
    would grow this table faster than the complaints it describes — and a reader has
    to know the record is partial rather than assume the tool returned little."""
    recorded = record_chat_turn(
        db_session, officer_id="o1", question="q", answer="a", duration_ms=10,
        tool_calls=[ToolCall(name="find_complaints", args={}, result="x" * 9000)],
    )
    stored = _steps(db_session, recorded.run_id)[1].output_summary
    assert len(stored) < 9000
    assert "truncated from 9000 characters" in stored


def test_a_tool_that_returned_nothing_records_an_empty_summary_not_none_text(db_session):
    recorded = record_chat_turn(
        db_session, officer_id="o1", question="q", answer="a", duration_ms=10,
        tool_calls=[ToolCall(name="search_policy", args={"query": "x"}, result=None)],
    )
    assert _steps(db_session, recorded.run_id)[1].output_summary == ""


def test_the_summary_limit_is_what_the_constant_says(db_session):
    """Guards against the limit drifting from its documentation."""
    recorded = record_chat_turn(
        db_session, officer_id="o1", question="q", answer="a", duration_ms=10,
        tool_calls=[ToolCall(name="find_complaints", args={}, result="y" * (SUMMARY_LIMIT + 50))],
    )
    stored = _steps(db_session, recorded.run_id)[1].output_summary
    assert stored.startswith("y" * SUMMARY_LIMIT)
