"""Rubric judges for the prose the deterministic metrics cannot reach.

Two artefacts get judged: the routing justification a citizen or officer reads to
understand why their complaint went where it did, and the daily briefing. Both are
free text, so accuracy has nothing to compare against — but "does this claim what
the evidence supports" is still answerable.

Three decisions worth stating:

- **One criterion per call.** Asking for five scores in one response correlates
  them: the model forms a single impression of the text and then fills in five
  numbers to match it. Separate calls cost more and produce scores that can
  actually disagree with each other.
- **Every criterion carries anchors** describing what a 1 and a 5 look like.
  Without them the same judge scores the same text differently on two runs, and
  agreement with a human is hopeless.
- **A judge failure scores None, never 1.** A judge outage is not a bad artefact,
  and scoring it as one would quietly punish the thing being judged for the
  judge's problem.

The scores mean nothing until `judge_validation` measures them against hand
labels. An unvalidated LLM judge is a number-shaped opinion.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Criterion:
    name: str
    description: str
    anchors: dict[int, str]
    """What a 1 and a 5 look like, at minimum. The judge prompt prints these."""


@dataclass
class JudgeScore:
    criterion: str
    score: int | None
    reasoning: str
    error: str | None = None

    def __post_init__(self):
        if self.score is not None and not 1 <= self.score <= 5:
            raise ValueError(f"a rubric score must be 1-5, got {self.score}")


CRITERIA: dict[str, list[Criterion]] = {
    "routing_justification": [
        Criterion(
            name="grounded",
            description="Every claim about ownership or scoring is supported by a cited "
                        "evidence item, and the citation says what the text says it says.",
            anchors={
                1: "asserts ownership with no citation, or cites an item that does not "
                   "support the claim",
                3: "cites evidence for the department but not for the contractor choice",
                5: "every factual claim carries a citation that genuinely supports it",
            },
        ),
        Criterion(
            name="complete",
            description="Names the department, the contractor, and why each was chosen.",
            anchors={
                1: "names neither, or only restates the complaint",
                3: "names the department and contractor but explains only one",
                5: "an officer could defend both choices from this text alone",
            },
        ),
        Criterion(
            name="restrained",
            description="Claims nothing the evidence does not establish — no invented "
                        "statutes, deadlines, names or figures.",
            anchors={
                1: "invents a specific fact (a rule number, a cost, a person)",
                3: "overstates confidence but invents nothing",
                5: "says plainly where the evidence stops",
            },
        ),
    ],
    "briefing": [
        Criterion(
            name="accurate",
            description="Consistent with the counts it was given; no figure appears that "
                        "was not supplied.",
            anchors={
                1: "states a number that contradicts or was not in the input",
                3: "all numbers correct but one is described misleadingly",
                5: "every figure traceable to the input, described correctly",
            },
        ),
        Criterion(
            name="actionable",
            description="The priorities name something specific a named officer could do "
                        "today.",
            anchors={
                1: "priorities are generic ('monitor the situation')",
                3: "specific but without saying what to do about it",
                5: "each priority names the thing and the action",
            },
        ),
        Criterion(
            name="proportionate",
            description="A quiet day reads as quiet; a bad day reads as bad.",
            anchors={
                1: "inflates a quiet day into an emergency, or buries a breach",
                3: "tone roughly right but hedged throughout",
                5: "the reader would correctly guess the numbers from the prose",
            },
        ),
    ],
}


def score_artifact(artifact_type: str, artifact: str, *, chain_factory: Callable,
                   evidence: str) -> list[JudgeScore]:
    """Score one artefact against every criterion for its type.

    `chain_factory(criterion_name)` returns the runnable for that criterion, so the
    caller decides whether the judge is a real model or a fake, and each criterion
    gets its own call.
    """
    if artifact_type not in CRITERIA:
        raise KeyError(f"unknown artifact type {artifact_type!r}; "
                       f"known: {sorted(CRITERIA)}")

    scores: list[JudgeScore] = []
    for criterion in CRITERIA[artifact_type]:
        try:
            result = chain_factory(criterion.name).invoke({
                "criterion": criterion.name,
                "criterion_description": criterion.description,
                "anchors": "\n".join(f"{value}: {text}"
                                     for value, text in sorted(criterion.anchors.items())),
                "artifact": artifact,
                "evidence": evidence,
            })
            scores.append(JudgeScore(criterion=criterion.name, score=result.score,
                                     reasoning=result.reasoning))
        except Exception as exc:
            # Not a 1: a judge outage says nothing about the artefact.
            logger.warning("judge failed on %s/%s", artifact_type, criterion.name, exc_info=True)
            scores.append(JudgeScore(criterion=criterion.name, score=None,
                                     reasoning="", error=f"{type(exc).__name__}: {exc}"))
    return scores


def judge_chain_factory(*, temperature: float = 0.0) -> Callable:
    """The real judge: one structured chain per criterion, uncached.

    Uncached for the same reason the eval configurations are: a cache keyed on the
    prompt would serve one criterion's verdict for another's, since the criterion
    arrives as a prompt variable rather than a separate prompt.
    """
    from app.ai.llm import Task, build_structured

    def factory(criterion_name: str):
        return build_structured(Task.NARRATE, _JudgeVerdict, "judge", cache=None)

    return factory


class _JudgeVerdict(BaseModel):
    """What the judge chain returns. Separate from JudgeScore, which carries the
    criterion name and the failure state the harness adds."""

    score: int = Field(ge=1, le=5, description="1-5 against the stated anchors")
    reasoning: str = Field(description="One sentence, quoting what decided it")
