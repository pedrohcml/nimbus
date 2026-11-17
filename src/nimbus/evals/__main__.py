import argparse
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import anyio
from dotenv import load_dotenv
from groq import AsyncGroq

from nimbus.agent.groq_llm import GroqLLM
from nimbus.agent.prompts import build_system_prompt
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


async def _run(cases: list[EvalCase], model: str, runs: int) -> list[RunResult]:
    client = AsyncGroq()

    def make_llm() -> GroqLLM:
        return GroqLLM(client, model)

    return await run_suite(cases, make_llm, runs=runs, on_result=_show)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nimbus eval suite.")
    parser.add_argument("--dataset", default="evals/datasets/v0.yaml")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument("--category", action="append", help="run only this category (repeatable)")
    parser.add_argument("--out", default="evals/reports")
    args = parser.parse_args()

    load_dotenv()
    cases = load_dataset(args.dataset)
    if args.case:
        cases = [case for case in cases if case.id in set(args.case)]
    if args.category:
        cases = [case for case in cases if case.category in set(args.category)]
    if not cases:
        raise SystemExit("No cases selected.")

    model = os.environ.get("NIMBUS_AGENT_MODEL", "openai/gpt-oss-120b")
    started = datetime.now(UTC)
    results = anyio.run(_run, cases, model, args.runs)

    meta = {
        "started_at": started.isoformat(timespec="seconds"),
        "model": model,
        "prompt_sha": hashlib.sha256(build_system_prompt(EVAL_NOW).encode()).hexdigest()[:12],
        "dataset": args.dataset,
        "runs": args.runs,
    }
    md_path, _ = write_report(
        Path(args.out), started.strftime("%Y%m%d-%H%M%S"), cases, results, meta
    )
    rate = pass_rate(results)
    print(f"\nPass rate: {'n/a' if rate is None else f'{rate:.0%}'}. Report: {md_path}")


if __name__ == "__main__":
    main()
