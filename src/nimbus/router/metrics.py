from collections.abc import Hashable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassScore:
    precision: float
    recall: float
    f1: float
    support: int


def accuracy(pairs: Iterable[tuple[Hashable, Hashable | None]]) -> float:
    pairs = list(pairs)
    if not pairs:
        return 0.0
    return sum(expected == predicted for expected, predicted in pairs) / len(pairs)


def class_scores(
    pairs: Iterable[tuple[Hashable, Hashable | None]], labels: Iterable[Hashable]
) -> dict[Hashable, ClassScore]:
    pairs = list(pairs)
    scores = {}
    for label in labels:
        hits = sum(e == label and p == label for e, p in pairs)
        predicted = sum(p == label for _, p in pairs)
        actual = sum(e == label for e, _ in pairs)
        precision = hits / predicted if predicted else 0.0
        recall = hits / actual if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[label] = ClassScore(precision, recall, f1, actual)
    return scores


def macro_f1(scores: dict[Hashable, ClassScore]) -> float:
    if not scores:
        return 0.0
    return sum(score.f1 for score in scores.values()) / len(scores)
