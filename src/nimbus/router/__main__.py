import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from dotenv import load_dotenv

from nimbus.agent.settings import router_model, router_reasoning_effort
from nimbus.router.evaluate import RouteOutcome, route_all, summarize
from nimbus.router.intents import INTENTS_DIR, IntentExample, load_examples
from nimbus.router.llm_router import ROUTER_PROMPT, build_router


def _show(outcome: RouteOutcome) -> None:
    mark = "ok" if outcome.predicted == outcome.example.intent else "XX"
    predicted = outcome.predicted or "ERROR"
    print(
        f"{mark} {outcome.elapsed_ms:6.0f} ms  {outcome.example.intent:<18} -> "
        f"{predicted:<18} {outcome.example.text[:60]}"
    )


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"\nAccuracy {summary['accuracy']:.1%}, macro F1 {summary['macro_f1']:.3f}, "
        f"errors {summary['errors']} (n={summary['n']})"
    )
    for group in ("by_language", "by_source"):
        rates = ", ".join(f"{name} {rate:.1%}" for name, rate in summary[group].items())
        print(f"{group.replace('_', ' ')}: {rates}")
    print(f"\n{'intent':<20}{'P':>6}{'R':>6}{'F1':>6}{'n':>5}")
    for name, score in summary["classes"].items():
        print(
            f"{name:<20}{score['precision']:>6.2f}{score['recall']:>6.2f}"
            f"{score['f1']:>6.2f}{score['support']:>5}"
        )
    latency, tokens = summary["latency_ms"], summary["tokens"]
    print(
        f"\nLatency p50 {latency['p50']:.0f} ms, p05 {latency['p95']:.0f} ms. "
        f"Tokens in {tokens['input_mean']:.0f}, out {tokens['output_mean']:.1f}."
    )


async def _run(examples: list[IntentExample]) -> list[RouteOutcome]:
    return await route_all(build_router(), examples, on_result=_show)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the intent router.")
    parser.add_argument("--data", default=str(INTENTS_DIR / "test.jsonl"))
    parser.add_argument("--misses", action="store_true", help="list every wrong route")
    parser.add_argument("--out", default="evals/reports")
    args = parser.parse_args()

    load_dotenv()
    examples = load_examples(Path(args.data))
    started = datetime.now(UTC)
    outcomes = anyio.run(_run, examples)
    summary = summarize(outcomes)

    _print_summary(summary)
    if args.misses:
        print("\nMisses:")
        for miss in summary["misses"]:
            print(
                f"  [{miss['language']}/{miss['source']}] {miss['expected']} -> "
                f"{miss['predicted']}: {miss['text']}"
            )

    meta = {
        "started_at": started.isoformat(timespec="seconds"),
        "model": router_model(),
        "reasoning_effort": router_reasoning_effort(),
        "prompt_sha": hashlib.sha256(ROUTER_PROMPT.encode()).hexdigest()[:12],
        "data": args.data,
    }
    path = Path(args.out) / f"router-{started:%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"meta": meta, "summary": summary}
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport: {path}")


if __name__ == "__main__":
    main()
