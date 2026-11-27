import pytest

from nimbus.router.evaluate import WARMUP_TEXT, RouteOutcome, percentile, route_all, summarize
from nimbus.router.intents import Intent, IntentExample
from nimbus.router.llm_router import RouterError, RouteResult


def example(text, intent, language="en", source="handwritten"):
    return IntentExample(text=text, intent=intent, language=language, source=source)


class FakeRouter:
    def __init__(self, answers):
        self.answers = answers
        self.texts = []

    async def route(self, text):
        self.texts.append(text)
        intent = self.answers.get(text, Intent.SMALLTALK)
        if intent is None:
            raise RouterError("invalid route: 'nope'")
        return RouteResult(intent, 100, 5)


def test_percentile_uses_nearest_rank():
    values = list(range(1, 11))
    assert percentile(values, 0.5) == 5
    assert percentile(values, 0.95) == 10
    assert percentile([], 0.5) == 0.0


@pytest.mark.anyio
async def test_warmup_call_not_measured():
    router = FakeRouter({"refund please": Intent.REFUND})
    examples = [example("refund please", Intent.REFUND)]

    outcomes = await route_all(router, examples)

    assert router.texts == [WARMUP_TEXT, "refund please"]
    assert len(outcomes) == 1
    assert outcomes[0].predicted is Intent.REFUND
    assert outcomes[0].elapsed_ms >= 0


@pytest.mark.anyio
async def test_router_error_becomes_failed_prediction():
    router = FakeRouter({"???": None})

    [outcome] = await route_all(router, [example("???", Intent.HUMAN)])

    assert outcome.predicted is None
    assert "invalid route" in outcome.error


@pytest.mark.anyio
async def test_each_outcome_reported():
    seen = []
    examples = [example("hi", Intent.SMALLTALK), example("oi", Intent.SMALLTALK, "pt")]

    await route_all(FakeRouter({}), examples, on_result=seen.append)

    assert [outcome.example.text for outcome in seen] == ["hi", "oi"]


def outcome(text, expected, predicted, language="en", source="handwritten", ms=100.0, error=None):
    return RouteOutcome(
        example(text, expected, language, source),
        predicted,
        ms,
        input_tokens=300,
        output_tokens=9,
        error=error,
    )


def test_summary_groups_accuracy_and_lists_misses():
    outcomes = [
        outcome("refund pls", Intent.REFUND, Intent.REFUND, ms=100),
        outcome("quero reembolso", Intent.REFUND, Intent.DISPUTE, "pt", "handwritten", ms=300),
        outcome("oi", Intent.SMALLTALK, Intent.SMALLTALK, "pt", ms=200),
        outcome(
            "???", Intent.HUMAN, None, source="handwritten", ms=400, error="invalid route: 'x'"
        ),
    ]

    summary = summarize(outcomes)

    assert summary["n"] == 4
    assert summary["accuracy"] == 0.5
    assert summary["errors"] == 1
    assert summary["by_language"] == {"en": 0.5, "pt": 0.5}
    assert summary["by_source"] == {"handwritten": 0.5}
    assert summary["classes"]["refund"]["recall"] == 0.5
    assert summary["latency_ms"] == {"p50": 200.0, "p95": 400.0}
    assert summary["tokens"] == {"input_mean": 300.0, "output_mean": 9.0}
    assert [miss["text"] for miss in summary["misses"]] == ["quero reembolso", "???"]
    assert summary["misses"][0]["predicted"] == "dispute"
    assert summary["misses"][1]["predicted"] is None
