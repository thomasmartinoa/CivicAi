"""Capturing judge artefacts out of the database."""

import json

from app.db.base import utcnow
from app.db.models.complaint import Complaint
from app.db.models.workflow import DailyBriefing
from app.evals.capture_artifacts import capture, main, write_jsonl


def _complaint(db_session, *, tracking, justification, evidence=None):
    complaint = Complaint(tracking_id=tracking, citizen_email="a@b.com",
                          description="pothole", category="ROADS",
                          routing_justification=justification, evidence=evidence or [])
    db_session.add(complaint)
    db_session.commit()
    return complaint


def test_routing_justifications_are_captured_with_only_their_own_evidence(db_session):
    """A labeller scoring "is this grounded" must see what route cited — and must
    not see work_order's chunks, which would invite scoring the wrong citations."""
    _complaint(db_session, tracking="CIV-CAP00001",
               justification="Public Works owns road surface defects [1].",
               evidence=[
                   {"node": "route", "source": "sop_roads.md",
                    "headers": ["Roads SOP", "Ownership"], "snippet": "Public Works owns roads."},
                   {"node": "work_order", "source": "rate_card.md",
                    "headers": ["Rate Card"], "snippet": "Rs 450 per m2"},
               ])

    artifacts = capture("routing_justification", session_factory=lambda: db_session)
    assert len(artifacts) == 1
    assert artifacts[0].id == "CIV-CAP00001"
    assert "Public Works owns road surface defects [1]." == artifacts[0].text
    assert "[1] sop_roads.md › Roads SOP › Ownership" in artifacts[0].evidence
    assert "rate_card" not in artifacts[0].evidence


def test_complaints_without_a_justification_are_skipped(db_session):
    _complaint(db_session, tracking="CIV-CAP00002", justification=None)
    assert capture("routing_justification", session_factory=lambda: db_session) == []


def test_an_ungrounded_justification_says_so_rather_than_showing_nothing(db_session):
    _complaint(db_session, tracking="CIV-CAP00003",
               justification="Public Works owns this.", evidence=[])
    artifacts = capture("routing_justification", session_factory=lambda: db_session)
    assert "No supporting documents were retrieved." in artifacts[0].evidence


def test_fallback_briefings_are_excluded(db_session):
    """Template text is not the model's prose, so scoring it would measure the
    fallback writer — which is a person."""
    db_session.add(DailyBriefing(brief_date=utcnow(), narrative="real narrative",
                                 new_complaints=4, is_fallback=False))
    db_session.add(DailyBriefing(brief_date=utcnow(), narrative="template text",
                                 new_complaints=1, is_fallback=True))
    db_session.commit()

    artifacts = capture("briefing", session_factory=lambda: db_session)
    assert [a.text for a in artifacts] == ["real narrative"]


def test_a_briefing_carries_its_counts_as_evidence(db_session):
    """The "accurate" criterion means agreeing with the numbers it was given, so a
    labeller cannot score it without them."""
    db_session.add(DailyBriefing(brief_date=utcnow(), narrative="Four new reports.",
                                 new_complaints=4, resolved_today=2, sla_at_risk=1,
                                 escalations_today=0, clusters_detected=1, is_fallback=False))
    db_session.commit()
    evidence = capture("briefing", session_factory=lambda: db_session)[0].evidence
    assert "new complaints: 4" in evidence
    assert "resolved: 2" in evidence


def test_the_limit_is_respected(db_session):
    for n in range(3):
        _complaint(db_session, tracking=f"CIV-CAP1000{n}", justification=f"because {n}")
    assert len(capture("routing_justification", session_factory=lambda: db_session, limit=2)) == 2


def test_the_file_is_the_shape_the_labeller_reads(tmp_path, db_session):
    from app.evals.label_judges import artifacts_for

    _complaint(db_session, tracking="CIV-CAP00009", justification="because [1].")
    path = tmp_path / "artifacts.jsonl"
    assert write_jsonl(capture("routing_justification",
                              session_factory=lambda: db_session), path) == 1

    row = json.loads(path.read_text().splitlines()[0])
    assert set(row) == {"id", "text", "evidence"}
    assert artifacts_for("routing_justification", path)[0].id == "CIV-CAP00009"


def test_an_empty_database_explains_what_to_do_instead_of_writing_nothing(
        db_session, monkeypatch, tmp_path, capsys):
    """And it must not offer to make some up."""
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: db_session)
    code = main(["--artifact-type", "briefing", "--out", str(tmp_path / "out.jsonl")])
    assert code == 2
    out = capsys.readouterr().out
    assert "no briefing artefacts" in out
    assert "real key" in out
    assert not (tmp_path / "out.jsonl").exists()
