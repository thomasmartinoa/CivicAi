"""Rubric judges, and the agreement that says whether to believe them.

An LLM judge nobody measured is a number-shaped opinion. These tests cover the
rubric mechanics and the agreement statistics; the hand labels themselves are the
author's work and cannot be generated, so the loader treats their absence as
"not validated" rather than inventing them.
"""

import pytest

from app.evals.judges import CRITERIA, JudgeScore, score_artifact
from app.evals.judge_validation import (
    KAPPA_FLOOR, ValidationReport, agreement, cohens_kappa, load_judge_labels,
)
from tests.ai.graph.conftest import raises, returns


def _score(criterion, value, reasoning="because"):
    return returns(JudgeScore(criterion=criterion, score=value, reasoning=reasoning))


# ── the rubric ──────────────────────────────────────────────────────────────


def test_both_artifact_types_have_criteria():
    assert set(CRITERIA) == {"routing_justification", "briefing"}
    for artifact, criteria in CRITERIA.items():
        assert len(criteria) >= 3, artifact
        assert all(c.name and c.description and c.anchors for c in criteria)


def test_each_criterion_states_what_a_1_and_a_5_look_like():
    """A rubric without anchors is a vibe with a number attached, and two runs of
    the same judge will not agree with each other, let alone with a human."""
    for criteria in CRITERIA.values():
        for criterion in criteria:
            assert 1 in criterion.anchors and 5 in criterion.anchors, criterion.name


def test_one_criterion_is_scored_per_call():
    """Asking for five criteria in one response correlates them into a single
    impression: the model decides whether it liked the text and then fills in five
    numbers to match."""
    calls = []

    def chain_for(criterion):
        def capture(payload):
            calls.append(payload["criterion"])
            return JudgeScore(criterion=criterion, score=4, reasoning="ok")
        from langchain_core.runnables import RunnableLambda
        return RunnableLambda(capture)

    scores = score_artifact("routing_justification", "Public Works owns this [1].",
                            chain_factory=chain_for, evidence="[1] sop_roads.md › Ownership")
    assert len(scores) == len(CRITERIA["routing_justification"])
    assert len(calls) == len(scores), "one call per criterion"
    assert len(set(calls)) == len(calls), "and a different criterion each time"


def test_the_judge_sees_the_evidence_it_is_asked_to_check_grounding_against():
    seen = {}

    def chain_for(criterion):
        from langchain_core.runnables import RunnableLambda

        def capture(payload):
            seen.update(payload)
            return JudgeScore(criterion=criterion, score=5, reasoning="grounded")
        return RunnableLambda(capture)

    score_artifact("routing_justification", "Public Works owns this [1].",
                   chain_factory=chain_for, evidence="[1] sop_roads.md › Ownership")
    assert "sop_roads.md" in seen["evidence"]
    assert "Public Works" in seen["artifact"]


def test_a_failed_criterion_is_recorded_as_unscored_not_as_one():
    """A judge outage is not a bad artifact. Scoring it 1 would quietly punish the
    thing being judged for the judge's failure."""
    def chain_for(criterion):
        return raises(RuntimeError("judge quota"))

    scores = score_artifact("briefing", "Four new reports.", chain_factory=chain_for, evidence="")
    assert all(s.score is None for s in scores)
    assert all("quota" in (s.error or "") for s in scores)


def test_an_out_of_range_score_is_refused():
    with pytest.raises(ValueError):
        JudgeScore(criterion="grounded", score=7, reasoning="x")


def test_an_unknown_artifact_type_raises():
    with pytest.raises(KeyError, match="unknown"):
        score_artifact("unknown", "x", chain_factory=lambda c: returns(None), evidence="")


# ── agreement with a human ──────────────────────────────────────────────────


def test_exact_and_within_one_agreement():
    judge = [3, 4, 5, 2]
    human = [3, 5, 5, 4]
    result = agreement(judge, human)
    assert result.exact == 0.5
    assert result.within_one == 0.75, "off-by-one matters on a five-point rubric"


def test_kappa_is_zero_for_chance_agreement_and_one_for_perfect():
    assert cohens_kappa([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    # Judge always says 5, human is split: agreement is no better than chance.
    assert cohens_kappa([5, 5, 5, 5], [5, 5, 1, 1]) <= 0.0


def test_a_judge_below_the_kappa_floor_is_flagged_not_dropped():
    """Dropping it hides that the criterion was measured badly; printing it
    silently implies it was measured well."""
    poor = ValidationReport.from_scores(criterion="grounded", judge=[5, 5, 5, 5],
                                        human=[5, 5, 1, 1])
    assert poor.reliable is False
    assert poor.kappa <= KAPPA_FLOOR
    assert "unreliable" in poor.summary.lower()

    good = ValidationReport.from_scores(criterion="grounded", judge=[1, 2, 3, 4, 5],
                                        human=[1, 2, 3, 4, 5])
    assert good.reliable is True


def test_agreement_needs_the_same_number_of_scores():
    with pytest.raises(ValueError, match="same length"):
        agreement([1, 2], [1])


def test_agreement_on_nothing_is_none_not_perfect():
    """Zero labelled items must not report perfect agreement."""
    result = agreement([], [])
    assert result.exact is None and result.within_one is None
    assert result.n == 0


def test_missing_hand_labels_mean_not_validated_rather_than_invented(tmp_path):
    """The labels are the author's judgement. The harness ships the format and the
    CLI; it must never generate them."""
    assert load_judge_labels(tmp_path / "absent.jsonl") == []


def test_hand_labels_round_trip(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text('{"artifact_type": "briefing", "artifact_id": "b-1", '
                    '"criterion": "accurate", "score": 4, "labeller": "author", '
                    '"labelled_at": "2026-09-28"}\n')
    labels = load_judge_labels(path)
    assert labels[0].score == 4
    assert labels[0].labeller == "author"


def test_a_label_without_a_labeller_is_refused(tmp_path):
    """Who scored it and when is part of the claim: judge agreement reported
    without a named labeller cannot be audited."""
    path = tmp_path / "labels.jsonl"
    path.write_text('{"artifact_type": "briefing", "artifact_id": "b-1", '
                    '"criterion": "accurate", "score": 4}\n')
    with pytest.raises(ValueError, match="labeller"):
        load_judge_labels(path)
