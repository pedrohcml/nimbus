import pytest

from nimbus.router.metrics import accuracy, class_scores, macro_f1

PAIRS = [("a", "a"), ("a", "b"), ("b", "b"), ("c", "b")]


def test_accuracy_counts_exact_matches():
    assert accuracy(PAIRS) == 0.5


def test_accuracy_of_nothing_equals_zero():
    assert accuracy([]) == 0.0


def test_failed_predicition_is_wrong():
    assert accuracy([("a", "a"), ("a", None)]) == 0.5


def test_class_scores():
    scores = class_scores(PAIRS, ["a", "b", "c"])

    assert scores["a"].precision == 1.0
    assert scores["a"].recall == 0.5
    assert scores["a"].f1 == pytest.approx(2 / 3)

    assert scores["b"].precision == pytest.approx(1 / 3)
    assert scores["b"].recall == 1.0
    assert scores["b"].f1 == pytest.approx(0.5)

    assert scores["c"].f1 == 0.0
    assert [scores[label].support for label in "abc"] == [2, 1, 1]


def test_macro_f1_mean_over_classes():
    scores = class_scores(PAIRS, ["a", "b", "c"])

    assert macro_f1(scores) == pytest.approx((2 / 3 + 0.5 + 0.0) / 3)
