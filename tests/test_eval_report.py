import json

from nimbus.evals.checks import CheckResult
from nimbus.evals.dataset import EvalCase, Turn
from nimbus.evals.report import pass_rate, render_markdown, summarize, write_report
from nimbus.evals.runner import RunResult, TurnResult

META = {
    "started_at": "2026-11-16T22:00:00+00:00",
    "model": "m",
    "prompt_sha": "abc",
    "dataset": "d",
    "runs": 3,
}


def run(case_id, status):
    result = RunResult(case_id=case_id, run_index=0)
    if status == "error":
        result.error = "RuntimeError: boom"
        return result
    check = CheckResult("answer_matches_any", status == "passed", "detail")
    result.turns.append(TurnResult(user="u", answer="a", checks=[check], trace=[]))
    return result


def case(case_id, category="lookup"):
    return EvalCase(id=case_id, category=category, turns=[Turn(user="u")])


def test_pass_rate_ignores_errors():
    assert pass_rate([run("a", "passed"), run("a", "failed"), run("a", "error")]) == 0.5


def test_pass_rate_is_none_when_everything_errored():
    assert pass_rate([run("a", "error")]) is None


def test_summary_per_case_and_category():
    cases = [case("a", "lookup"), case("b", "security")]
    results = [run("a", "passed"), run("a", "passed"), run("b", "failed")]
    summary = summarize(cases, results)
    assert summary["categories"] == {"lookup": 1.0, "security": 0.0}
    row_b = next(row for row in summary["cases"] if row["id"] == "b")
    assert row_b["top_failures"] == [("answer_matches_any", 1)]


def test_markdown_shows_cases_rates_and_escapes_pipes():
    cases = [case("a"), case("b")]
    failing = run("b", "failed")
    failing.turns[0].checks[0] = CheckResult("answer_matches_none:(yes|no)", False)
    summary = summarize(cases, [run("a", "passed"), failing])
    text = render_markdown(summary, META)
    assert "| a |" in text
    assert "50%" in text
    assert r"(yes\|no)" in text


def test_write_report_creates_markdown_and_json(tmp_path):
    md_path, json_path = write_report(tmp_path, "run1", [case("a")], [run("a", "passed")], META)
    assert md_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["results"][0]["status"] == "passed"
