"""Evaluation metrics, as pure functions over plain lists.

Written by hand rather than imported from scikit-learn. Each one is a handful of
lines, the dependency would be the heaviest import in this tree, and — the real
reason — two of the choices here are arguable and a project that publishes
macro-F1 should be able to state them:

1. **A class the model never predicts scores F1 0, not "skipped".** Its precision
   is 0/0. Counting it as zero drags the macro average down; skipping it would
   flatter a model that ignores a rare category. A classifier that never emits
   FIRE_HAZARD is broken in exactly the way macro-F1 exists to expose.
2. **A metric over an empty sample is None, not 0.0.** In a report, 0.00 reads as
   "measured, and a total failure". Nothing was measured, and the cell must say
   so — see the "never invent a number" constraint in the Phase 3 plan.

Percentiles use nearest-rank, so p95 of twenty observed latencies is one of the
twenty. Interpolating would report a duration nothing actually took.
"""

import math
from dataclasses import dataclass


def _same_length(truth: list, predicted: list) -> None:
    if len(truth) != len(predicted):
        raise ValueError(
            f"truth and predicted must be the same length, got {len(truth)} and {len(predicted)}"
        )


@dataclass(frozen=True)
class ClassScores:
    precision: float
    recall: float
    f1: float
    support: int
    """How many items of this class the dataset actually holds. A precision of
    1.00 on support 1 is not the same claim as on support 40, and a report that
    omits support invites reading them alike."""


def accuracy(truth: list, predicted: list) -> float | None:
    """The share of items that matched. None on an empty sample."""
    _same_length(truth, predicted)
    if not truth:
        return None
    return sum(1 for t, p in zip(truth, predicted) if t == p) / len(truth)


def confusion_matrix(truth: list, predicted: list, *, labels: list) -> dict[str, dict[str, int]]:
    """`matrix[actual][predicted]` counts, covering every label in `labels`.

    Unseen labels are still rows and columns: a category that never came up must
    not silently disappear from the report. A *prediction* outside `labels` is an
    error rather than a new row — a model inventing a category is a bug to
    surface, not a cell to add.
    """
    _same_length(truth, predicted)
    known = set(labels)
    unknown = {v for v in (*truth, *predicted) if v is not None and v not in known}
    if unknown:
        raise ValueError(f"values outside the label set: {sorted(unknown)}")

    matrix = {actual: dict.fromkeys(labels, 0) for actual in labels}
    for actual, prediction in zip(truth, predicted):
        if actual is None or prediction is None:
            continue
        matrix[actual][prediction] += 1
    return matrix


def per_class_prf(truth: list, predicted: list, *, labels: list) -> dict[str, ClassScores]:
    """Precision, recall, F1 and support for each label.

    0/0 becomes 0.0 here, deliberately — see the module docstring. The `support`
    field is how a reader tells a meaningful 1.00 from an accidental one.
    """
    _same_length(truth, predicted)
    scores: dict[str, ClassScores] = {}
    for label in labels:
        true_positive = sum(1 for t, p in zip(truth, predicted) if t == label and p == label)
        false_positive = sum(1 for t, p in zip(truth, predicted) if t != label and p == label)
        false_negative = sum(1 for t, p in zip(truth, predicted) if t == label and p != label)

        precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
        recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        scores[label] = ClassScores(precision=precision, recall=recall, f1=f1,
                                    support=true_positive + false_negative)
    return scores


def macro_f1(truth: list, predicted: list, *, labels: list) -> float | None:
    """The unweighted mean F1 across every label.

    Unweighted on purpose: eleven correct ROADS and one missed FIRE_HAZARD is not
    92%. Macro-F1 averages over classes, not items, so a rare category the model
    cannot do costs half the score in a two-class set — which is the number this
    project wants to be judged on, given twelve categories of wildly different
    frequency.
    """
    _same_length(truth, predicted)
    if not truth:
        return None
    scores = per_class_prf(truth, predicted, labels=labels)
    return sum(s.f1 for s in scores.values()) / len(labels)


def mean_absolute_error(truth: list[float], predicted: list[float]) -> float | None:
    """Mean |error|, in the unit of the score.

    Not RMSE: priority is read as "typically eleven points out", and squaring
    would make the number unreadable in exchange for punishing outliers, which
    the confusion matrix already shows.
    """
    _same_length(truth, predicted)
    if not truth:
        return None
    return sum(abs(t - p) for t, p in zip(truth, predicted)) / len(truth)


def precision_recall(truth: list[bool], predicted: list[bool], *, positive: bool) -> tuple[float | None, float | None]:
    """Precision and recall for one side of a binary decision.

    `positive=False` scores the "this is junk" call, which is the one that costs a
    citizen a real complaint. Precision is None when nothing was predicted
    positive — reporting 0.0 would imply the model tried and failed, when it never
    tried.
    """
    _same_length(truth, predicted)
    if not truth:
        return None, None
    true_positive = sum(1 for t, p in zip(truth, predicted) if t == positive and p == positive)
    predicted_positive = sum(1 for p in predicted if p == positive)
    actual_positive = sum(1 for t in truth if t == positive)

    precision = true_positive / predicted_positive if predicted_positive else None
    recall = true_positive / actual_positive if actual_positive else None
    return precision, recall


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile: the returned value is one of the inputs.

    p95 of twenty latencies is the 19th slowest, not an interpolation between the
    19th and 20th. A report that quotes a duration nothing took is hard to defend
    and impossible to reproduce by hand.
    """
    if not 0 < p <= 100:
        raise ValueError(f"percentile must be in (0, 100], got {p}")
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(p / 100 * len(ordered))
    return ordered[max(0, rank - 1)]
