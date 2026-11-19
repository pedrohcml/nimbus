import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import anyio
from dotenv import load_dotenv
from groq import AsyncGroq

from nimbus.agent.groq_llm import GroqLLM
from nimbus.agent.prompts import build_system_prompt
from nimbus.agent.settings import agent_model, groq_api_key, sampling_options
from nimbus.evals.dataset import EvalCase, load_dataset
from nimbus.evals.report import pass_rate, write_report
from nimbus.evals.runner import EVAL_NOW, RunResult, run_suite


def _show(result: RunResult) -> None:
    line = f"{result.case_id} [run {result.run_index}] {result.status}"
    if result.status == "failed":
        line += " -> " + ", ".join(check.name for check in result.failed_checks)
    elif result.status == "error":
        line += f" -> {result.error}"
    print(line)


async def _run(cases: list[EvalCase], model: str, runs: int, pause_s: float) -> list[RunResult]:
    client = AsyncGroq(api_key=groq_api_key(), max_retries=6)

    def make_llm() -> GroqLLM:
        return GroqLLM(client, model, **sampling_options())

    return await run_suite(cases, make_llm, runs=runs, pause_s=pause_s, on_result=_show)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nimbus eval suite.")
    parser.add_argument("--dataset", default="evals/datasets/v0.yaml")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument("--category", action="append", help="run only this category (repeatable)")
    parser.add_argument("--out", default="evals/reports")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds to wait between runs")
    args = parser.parse_args()

    load_dotenv()
    cases = load_dataset(args.dataset)
    if args.case:
        cases = [case for case in cases if case.id in set(args.case)]
    if args.category:
        cases = [case for case in cases if case.category in set(args.category)]
    if not cases:
        raise SystemExit("No cases selected.")

    started = datetime.now(UTC)
    results = anyio.run(_run, cases, agent_model(), args.runs, args.pause)

    meta = {
        "started_at": started.isoformat(timespec="seconds"),
        "model": agent_model(),
        "prompt_sha": hashlib.sha256(build_system_prompt(EVAL_NOW).encode()).hexdigest()[:12],
        "dataset": args.dataset,
        "runs": args.runs,
    }
    md_path, _ = write_report(
        Path(args.out), started.strftime("%Y%m%d-%H%M%S"), cases, results, meta
    )
    rate = pass_rate(results)
    print(f"\nPass rate: {'n/a' if rate is None else f'{rate:.0%}'}. Report: {md_path}")
    if len(results) < len(cases) * args.runs:
        print(
            f"Stopped early after repeated errors: {len(results)} of {len(cases) * args.runs} runs."
        )


if __name__ == "__main__":
    main()
