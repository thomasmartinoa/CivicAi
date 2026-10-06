"""Metrics, and the judgement calls inside them.

Every one of these is a handful of lines, which is why they are written here
rather than pulled from scikit-learn — but the real reason is that two of the
choices below are arguable, and a project that reports macro-F1 should be able to
say out loud how it treats a class the model never predicted.
"""

import pytest

from app.evals.metrics import (
    accuracy, confusion_matrix, macro_f1, mean_absolute_error, per_class_prf,
    percentile, precision_recall,
)


def test_accuracy_is_the_share_that_matched():
    assert accuracy(["a", "b", "c", "d"], ["a", "b", "c", "x"]) == 0.75
    assert accuracy(["a"], ["a"]) == 1.0
    assert accuracy(["a"], ["b"]) == 0.0


def test_metrics_on_an_empty_sample_are_none_not_zero():
    """0.00 in a report reads as "measured, and a total failure". Nothing was
    measured, so the cell must say so."""
    assert accuracy([], []) is None
    assert macro_f1([], [], labels=["ROADS"]) is None
    assert mean_absolute_error([], []) is None
    assert percentile([], 95) is None
    assert precision_recall([], [], positive=True) == (None, None)


def test_mismatched_lengths_raise():
    """zip() would silently truncate, scoring a subset and reporting the whole."""
    with pytest.raises(ValueError, match="same length"):
        accuracy(["a", "b"], ["a"])
    with pytest.raises(ValueError, match="same length"):
        mean_absolute_error([1, 2], [1])


def test_the_confusion_matrix_counts_truth_by_prediction():
    matrix = confusion_matrix(
        ["ROADS", "ROADS", "WATER", "WATER"],
        ["ROADS", "WATER", "WATER", "WATER"],
        labels=["ROADS", "WATER"],
    )
    assert matrix["ROADS"]["ROADS"] == 1
    assert matrix["ROADS"]["WATER"] == 1, "a ROADS complaint called WATER"
    assert matrix["WATER"]["WATER"] == 2
    assert matrix["WATER"]["ROADS"] == 0


def test_the_confusion_matrix_covers_every_label_even_unseen_ones():
    """A category that never appears must still be a row and a column, or the
    report silently narrows to what happened to come up."""
    matrix = confusion_matrix(["ROADS"], ["ROADS"], labels=["ROADS", "FIRE_HAZARD"])
    assert set(matrix) == {"ROADS", "FIRE_HAZARD"}
    assert matrix["FIRE_HAZARD"] == {"ROADS": 0, "FIRE_HAZARD": 0}


def test_a_prediction_outside_the_label_set_is_refused():
    """A model returning a category the dataset does not know about is a bug to
    surface, not a row to quietly add."""
    with pytest.raises(ValueError, match="SEWAGE"):
        confusion_matrix(["ROADS"], ["SEWAGE"], labels=["ROADS", "WATER"])


def test_per_class_precision_recall_and_f1():
    truth = ["ROADS", "ROADS", "ROADS", "WATER"]
    predicted = ["ROADS", "ROADS", "WATER", "WATER"]
    scores = per_class_prf(truth, predicted, labels=["ROADS", "WATER"])
    assert scores["ROADS"].precision == 1.0
    assert scores["ROADS"].recall == pytest.approx(2 / 3)
    assert scores["ROADS"].support == 3
    assert scores["WATER"].precision == 0.5
    assert scores["WATER"].recall == 1.0


def test_macro_f1_counts_a_never_predicted_class_as_zero():
    """The judgement call, pinned. FIRE_HAZARD is in the labels and never
    predicted, so its precision is 0/0. Counting that as zero drags the macro
    average down, which is the point of macro-F1: a classifier that never emits a
    rare category is broken in exactly the way the metric exists to expose.
    Skipping the class would flatter it to 0.8."""
    truth = ["ROADS", "ROADS", "FIRE_HAZARD"]
    predicted = ["ROADS", "ROADS", "ROADS"]
    assert macro_f1(truth, predicted, labels=["ROADS", "FIRE_HAZARD"]) == pytest.approx(0.4)


def test_macro_f1_weights_every_class_equally_regardless_of_support():
    """Eleven ROADS right and one FIRE_HAZARD wrong is not 92%: macro-F1 is the
    mean over classes, not over items, so the rare failure costs half the score."""
    truth = ["ROADS"] * 11 + ["FIRE_HAZARD"]
    predicted = ["ROADS"] * 12
    assert accuracy(truth, predicted) == pytest.approx(11 / 12)
    assert macro_f1(truth, predicted, labels=["ROADS", "FIRE_HAZARD"]) < 0.5


def test_macro_f1_is_one_for_a_perfect_classifier():
    truth = ["ROADS", "WATER", "SEWAGE"]
    assert macro_f1(truth, truth, labels=["ROADS", "WATER", "SEWAGE"]) == 1.0


def test_mean_absolute_error_is_in_the_unit_of_the_score():
    """Priority MAE is "points of priority", so no squaring and no scaling: an
    officer reads it as "typically eleven points out"."""
    assert mean_absolute_error([50, 60], [60, 50]) == 10.0
    assert mean_absolute_error([50], [50]) == 0.0


def test_precision_and_recall_for_the_invalid_complaint_check():
    """Validity is the one binary decision in the pipeline. Rejecting a real
    complaint is the expensive error, so both numbers are reported."""
    truth = [True, True, False, False]           # two genuine, two junk
    predicted = [True, False, False, True]       # one genuine rejected, one junk let through
    precision, recall = precision_recall(truth, predicted, positive=False)
    assert precision == 0.5, "of two 'junk' calls, one was actually genuine"
    assert recall == 0.5, "of two junk items, one was caught"


def test_precision_is_none_when_nothing_was_predicted_positive():
    """Not 0.0: a model that never says "junk" has undefined precision on junk,
    and reporting zero implies it tried and failed."""
    precision, recall = precision_recall([True, False], [True, True], positive=False)
    assert precision is None
    assert recall == 0.0


def test_percentile_is_a_nearest_rank_sample_not_an_interpolation():
    """p95 of twenty observed latencies must be one of them. Interpolating
    invents a duration nothing took."""
    values = list(range(1, 21))          # 1..20
    assert percentile(values, 95) == 19
    assert percentile(values, 50) == 10
    assert percentile(values, 100) == 20
    assert percentile([7], 95) == 7


def test_percentile_ignores_input_order():
    assert percentile([9, 1, 5], 50) == percentile([1, 5, 9], 50)


def test_an_out_of_range_percentile_raises():
    with pytest.raises(ValueError):
        percentile([1, 2, 3], 0)
    with pytest.raises(ValueError):
        percentile([1, 2, 3], 101)
