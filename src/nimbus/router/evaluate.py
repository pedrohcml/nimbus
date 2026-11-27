import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Protocol

from nimbus.router.intents import Intent, IntentExample
from nimbus.router.llm_router import RouterError, RouteResult
from nimbus.router.metrics import accuracy, class_scores, macro_f1

WARMUP_TEXT = "hello"


class Router(Protocol):
    async def route(self, text: str) -> RouteResult: ...


@dataclass(frozen=True)
class RouteOutcome:
    example: IntentExample
    predicted: Intent | None
    elapsed_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def percentile(values: Iterable[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


async def route_all(
    router: Router,
    examples: Iterable[IntentExample],
    *,
    warmup: bool = True,
    on_result: Callable[[RouteOutcome], None] | None = None,
) -> list[RouteOutcome]:
    if warmup:
        try:
            await router.route(WARMUP_TEXT)
        except RouterError:
            pass
    outcomes = []
    for example in examples:
        started = time.perf_counter()
        try:
            result = await router.route(example.text)
        except RouterError as error:
            outcome = RouteOutcome(example, None, _ms(started), error=str(error))
        else:
            outcome = RouteOutcome(
                example, result.intent, _ms(started), result.input_tokens, result.output_tokens
            )
        outcomes.append(outcome)
        if on_result:
            on_result(outcome)
    return outcomes


def _pairs(outcomes: list[RouteOutcome]) -> list[tuple[Intent, Intent | None]]:
    return [(outcome.example.intent, outcome.predicted) for outcome in outcomes]


def _accuracy_by(
    outcomes: list[RouteOutcome], key: Callable[[IntentExample], str]
) -> dict[str, float]:
    groups: dict[str, list[RouteOutcome]] = defaultdict(list)
    for outcome in outcomes:
        groups[key(outcome.example)].append(outcome)
    return {name: accuracy(_pairs(group)) for name, group in sorted(groups.items())}


def summarize(outcomes: list[RouteOutcome]) -> dict[str, Any]:
    pairs = _pairs(outcomes)
    scores = class_scores(pairs, list(Intent))
    latencies = [outcome.elapsed_ms for outcome in outcomes]
    return {
        "n": len(outcomes),
        "accuracy": accuracy(pairs),
        "macro_f1": macro_f1(scores),
        "errors": sum(outcome.error is not None for outcome in outcomes),
        "by_language": _accuracy_by(outcomes, lambda e: e.language),
        "by_source": _accuracy_by(outcomes, lambda e: e.source),
        "classes": {intent.value: asdict(score) for intent, score in scores.items()},
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)},
        "tokens": {
            "input_mean": fmean(o.input_tokens for o in outcomes) if outcomes else 0.0,
            "output_mean": fmean(o.output_tokens for o in outcomes) if outcomes else 0.0,
        },
        "misses": [
            {
                "text": outcome.example.text,
                "expected": outcome.example.intent.value,
                "predicted": outcome.predicted.value if outcome.predicted else None,
                "language": outcome.example.language,
                "source": outcome.example.source,
                "error": outcome.error,
            }
            for outcome in outcomes
            if outcome.predicted != outcome.example.intent
        ],
    }
