import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from nimbus.evals.dataset import EvalCase
from nimbus.evals.runner import RunResult


def pass_rate(results: list[RunResult]) -> float | None:
    graded = [result for result in results if result.status != "error"]
    if not graded:
        return None
    return sum(result.status == "passed" for result in graded) / len(graded)


def summarize(cases: list[EvalCase], results: list[RunResult]) -> dict[str, Any]:
    by_case: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        by_case[result.case_id].append(result)

    rows = []
    for case in cases:
        runs = by_case.get(case.id, [])
        failing = Counter(check.name for run in runs for check in run.failed_checks)
        rows.append(
            {
                "id": case.id,
                "category": case.category,
                "runs": len(runs),
                "passed": sum(run.status == "passed" for run in runs),
                "failed": sum(run.status == "failed" for run in runs),
                "errors": sum(run.status == "error" for run in runs),
                "pass_rate": pass_rate(runs),
                "top_failures": failing.most_common(3),
            }
        )

    categories = {}
    for category in sorted({case.category for case in cases}):
        ids = {case.id for case in cases if case.category == category}
        categories[category] = pass_rate([r for r in results if r.case_id in ids])

    return {
        "overall": pass_rate(results),
        "runs": len(results),
        "errors": sum(result.status == "error" for result in results),
        "categories": categories,
        "cases": rows,
    }


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.0%}"


def _escape(text: str) -> str:
    return text.replace("|", r"\|")


def render_markdown(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    lines = [
        f"# Eval report {meta['started_at']}",
        "",
        f"- Model: '{meta['model']}'",
        f"- Prompt: '{meta['prompt_sha']}'",
        f"- Dataset: '{meta['dataset']}' ({len(summary['cases'])} cases, {meta['runs']} runs each)",
        "",
        f"**Pass rate: {_pct(summary['overall'])}**"
        f"({summary['errors']} runs with errors, not counted)",
        "",
        "| Category | Pass rate |",
        "|---|---|",
    ]
    lines += [f"| {category} | {_pct(rate)} |" for category, rate in summary["categories"].items()]
    lines += [
        "",
        "| Case | Category | Passed | Errors | Top failing checks |",
        "|---|---|---|---|---|",
    ]
    for row in summary["cases"]:
        failures = (
            "<br>".join(f"'{_escape(name)}' x{count}" for name, count in row["top_failures"]) or "-"
        )
        lines.append(
            f"| {row['id']} | {row['category']} | {row['passed']}/{row['runs']} "
            f"| {row['errors']} | {failures} |"
        )
    return "\n".join(lines) + "\n"


def write_report(
    out_dir: Path,
    name: str,
    cases: list[EvalCase],
    results: list[RunResult],
    meta: dict[str, Any],
) -> tuple[Path, Path]:
    summary = summarize(cases, results)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{name}.md"
    json_path = out_dir / f"{name}.json"
    md_path.write_text(render_markdown(summary, meta), encoding="utf-8")
    payload = {
        "meta": meta,
        "summary": summary,
        "results": [asdict(result) | {"status": result.status} for result in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path
