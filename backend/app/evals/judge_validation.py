"""Measure the judges against hand labels, so their scores come with bounds.

An LLM judge nobody checked is a number-shaped opinion. Twenty hand-scored items
per criterion give three statistics: exact agreement, within-one agreement, and
Cohen's κ. A criterion whose κ falls below KAPPA_FLOOR is reported as unreliable
and its scores are printed *with that warning attached* — dropping it would hide
that the criterion was measured badly, and printing it silently would imply it was
measured well.

**The labels are the author's judgement and this module never generates them.** It
ships the format, the loader and the agreement maths; `--label` walks a human
through scoring. A missing labels file means "not validated", which the report
says out loud.

Known limitation, stated rather than hidden: κ here is unweighted, so it treats a
4-vs-5 disagreement exactly as harshly as 1-vs-5. On an ordinal rubric a
linear-weighted κ would be fairer to the judge. Within-one agreement is reported
alongside precisely because it carries the information unweighted κ throws away.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

KAPPA_FLOOR = 0.4
"""Below this, agreement is too weak to present the judge's scores as findings.
0.4 is the conventional boundary between "fair" and "moderate" agreement; it is a
convention, not a law, and the report prints κ so a reader can disagree."""

DEFAULT_LABELS = Path(__file__).parent / "dataset" / "judge_labels_v1.jsonl"


@dataclass(frozen=True)
class HandLabel:
    artifact_type: str
    artifact_id: str
    criterion: str
    score: int
    labeller: str
    labelled_at: str | None = None


@dataclass(frozen=True)
class Agreement:
    n: int
    exact: float | None
    within_one: float | None


def load_judge_labels(path: Path = DEFAULT_LABELS) -> list[HandLabel]:
    """Hand labels, or an empty list when none have been written yet.

    Empty means "not validated" — never an excuse to synthesise labels.
    """
    path = Path(path)
    if not path.exists():
        logger.info("no judge labels at %s; judge scores will be reported as not validated", path)
        return []

    labels: list[HandLabel] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("labeller"):
            raise ValueError(
                f"{path.name} line {number}: every label needs a 'labeller' — agreement "
                "reported without naming who scored it cannot be audited"
            )
        labels.append(HandLabel(
            artifact_type=row["artifact_type"],
            artifact_id=row["artifact_id"],
            criterion=row["criterion"],
            score=int(row["score"]),
            labeller=row["labeller"],
            labelled_at=row.get("labelled_at"),
        ))
    return labels


def agreement(judge: list[int], human: list[int]) -> Agreement:
    """Exact and within-one agreement. None on an empty sample, not 1.0."""
    if len(judge) != len(human):
        raise ValueError(f"judge and human scores must be the same length, "
                         f"got {len(judge)} and {len(human)}")
    if not judge:
        return Agreement(n=0, exact=None, within_one=None)
    exact = sum(1 for j, h in zip(judge, human) if j == h) / len(judge)
    within = sum(1 for j, h in zip(judge, human) if abs(j - h) <= 1) / len(judge)
    return Agreement(n=len(judge), exact=exact, within_one=within)


def cohens_kappa(judge: list[int], human: list[int]) -> float:
    """Unweighted Cohen's κ: agreement above what chance would give.

    See the module docstring on why unweighted is a compromise here.
    """
    if len(judge) != len(human):
        raise ValueError("judge and human scores must be the same length")
    if not judge:
        return 0.0

    n = len(judge)
    observed = sum(1 for j, h in zip(judge, human) if j == h) / n
    categories = set(judge) | set(human)
    expected = sum((judge.count(c) / n) * (human.count(c) / n) for c in categories)
    if expected == 1.0:
        # Both raters gave the same single value to everything: chance agreement is
        # total, so κ is undefined. Report 1.0 only when they actually agreed.
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


@dataclass(frozen=True)
class ValidationReport:
    criterion: str
    agreement: Agreement
    kappa: float
    reliable: bool
    summary: str

    @classmethod
    def from_scores(cls, *, criterion: str, judge: list[int], human: list[int]) -> "ValidationReport":
        scores = agreement(judge, human)
        kappa = cohens_kappa(judge, human)
        reliable = kappa > KAPPA_FLOOR and scores.n > 0
        if scores.n == 0:
            summary = f"{criterion}: not validated — no hand labels"
        elif reliable:
            summary = (f"{criterion}: κ={kappa:.2f} over {scores.n} labels "
                       f"(exact {scores.exact:.0%}, within one {scores.within_one:.0%})")
        else:
            summary = (f"{criterion}: UNRELIABLE, κ={kappa:.2f} over {scores.n} labels "
                       f"(exact {scores.exact:.0%}, within one {scores.within_one:.0%}) — "
                       f"below the {KAPPA_FLOOR} floor, so treat its scores as indicative only")
        return cls(criterion=criterion, agreement=scores, kappa=kappa,
                   reliable=reliable, summary=summary)
