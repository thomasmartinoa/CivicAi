"""The labelling CLI. Driven with fake input, so no human is needed to test it."""

import json

import pytest

from app.evals.judge_validation import load_judge_labels
from app.evals.label_judges import (
    Artifact, TARGET_PER_CRITERION, artifacts_for, label, main, progress,
)
from app.evals.judges import CRITERIA


@pytest.fixture
def answers(monkeypatch):
    """Feed keystrokes to the prompt."""
    queued = []

    def fake_input(_prompt=""):
        if not queued:
            raise EOFError
        return queued.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return queued


def _artifacts(n=2):
    return [Artifact(id=f"a-{i}", text=f"text {i}", evidence=f"[1] source {i}")
            for i in range(n)]


def test_each_answer_becomes_a_label_row(answers, tmp_path, capsys):
    path = tmp_path / "labels.jsonl"
    criteria = CRITERIA["briefing"]
    answers.extend(["4"] * len(criteria))

    added = label(artifact_type="briefing", artifacts=_artifacts(1), path=path,
                  labeller="tester")
    assert added == len(criteria)

    labels = load_judge_labels(path)
    assert {label_.criterion for label_ in labels} == {c.name for c in criteria}
    assert all(label_.score == 4 for label_ in labels)
    assert all(label_.labeller == "tester" for label_ in labels)
    assert all(label_.labelled_at for label_ in labels)


def test_the_rubric_and_its_anchors_are_shown(answers, tmp_path, capsys):
    answers.extend(["3"] * len(CRITERIA["routing_justification"]))
    label(artifact_type="routing_justification", artifacts=_artifacts(1),
          path=tmp_path / "l.jsonl", labeller="tester")
    out = capsys.readouterr().out
    first = CRITERIA["routing_justification"][0]
    assert first.name in out
    assert first.anchors[1] in out, "a scale with no anchors is a vibe with a number"
    assert first.anchors[5] in out
    assert "[1] source 0" in out, "the evidence has to be visible to judge grounding"


def test_q_stops_immediately_and_keeps_what_was_scored(answers, tmp_path):
    path = tmp_path / "labels.jsonl"
    answers.extend(["5", "q"])
    added = label(artifact_type="briefing", artifacts=_artifacts(3), path=path,
                  labeller="tester")
    assert added == 1
    assert len(load_judge_labels(path)) == 1, "quitting must not lose the first answer"


def test_s_skips_one_criterion_without_recording_a_score(answers, tmp_path):
    path = tmp_path / "labels.jsonl"
    criteria = CRITERIA["briefing"]
    answers.extend(["s"] + ["2"] * (len(criteria) - 1))
    added = label(artifact_type="briefing", artifacts=_artifacts(1), path=path,
                  labeller="tester")
    assert added == len(criteria) - 1


def test_a_bad_keystroke_reprompts_rather_than_recording_something(answers, tmp_path, capsys):
    path = tmp_path / "labels.jsonl"
    answers.extend(["9", "banana", "3", "q"])
    label(artifact_type="briefing", artifacts=_artifacts(1), path=path, labeller="tester")
    assert [l.score for l in load_judge_labels(path)] == [3]
    assert "a digit 1-5" in capsys.readouterr().out


def test_work_already_done_is_skipped(answers, tmp_path):
    """Twenty labels in four sittings: a second pass must not ask again."""
    path = tmp_path / "labels.jsonl"
    criteria = CRITERIA["briefing"]
    answers.extend(["4"] * len(criteria))
    label(artifact_type="briefing", artifacts=_artifacts(1), path=path, labeller="tester")

    assert label(artifact_type="briefing", artifacts=_artifacts(1), path=path,
                 labeller="tester") == 0
    assert len(load_judge_labels(path)) == len(criteria), "nothing was duplicated"


def test_progress_shows_what_is_left(tmp_path, answers):
    path = tmp_path / "labels.jsonl"
    answers.extend(["4"] * len(CRITERIA["briefing"]))
    label(artifact_type="briefing", artifacts=_artifacts(1), path=path, labeller="tester")
    counts = progress(path, "briefing")
    assert all(n == 1 for n in counts.values())
    assert TARGET_PER_CRITERION == 20


def test_the_cli_refuses_to_run_without_a_labeller(tmp_path, capsys):
    code = main(["--artifact-type", "briefing", "--labels", str(tmp_path / "l.jsonl")])
    assert code == 2
    assert "labeller is required" in capsys.readouterr().err


def test_the_cli_refuses_to_invent_artefacts(tmp_path, capsys):
    """Judging prose nobody's system wrote tells you nothing about the prose it
    does write."""
    code = main(["--artifact-type", "briefing", "--labeller", "tester",
                 "--labels", str(tmp_path / "l.jsonl")])
    assert code == 2
    assert "real run" in capsys.readouterr().err


def test_artefacts_are_read_from_a_jsonl(tmp_path):
    source = tmp_path / "artifacts.jsonl"
    source.write_text(json.dumps({"id": "b-1", "text": "Four new reports.",
                                  "evidence": "[1] sla_policy.md"}) + "\n")
    items = artifacts_for("briefing", source)
    assert items[0].id == "b-1" and items[0].evidence == "[1] sla_policy.md"
    assert artifacts_for("briefing", tmp_path / "absent.jsonl") == []


def test_status_reports_without_asking_anything(tmp_path, capsys):
    code = main(["--artifact-type", "briefing", "--status",
                 "--labels", str(tmp_path / "l.jsonl")])
    assert code == 0
    assert "accurate 0/20" in capsys.readouterr().out
