import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from nimbus.agent.language import detect_language
from nimbus.evals.dataset import DbCheck, TurnExpect

TX_ID = re.compile(r"tx_[A-Za-z0-9_]+")


INTERNAL_TERMS = (
    "amount_minor",
    "fee_minor",
    "pending_approval",
    "requires_approval",
    "counterparty_memo",
    "tool_call",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def ids_in(text: str) -> set[str]:
    return set(TX_ID.findall(text))


def _tool_results(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in trace if event["type"] == "tool_result"]


def _stop_reason(trace: list[dict[str, Any]]) -> str | None:
    return next(
        (event["stop_reason"] for event in reversed(trace) if event["type"] == "turn_end"),
        None,
    )


def check_turn(
    expect: TurnExpect,
    trace: list[dict[str, Any]],
    answer: str,
    known_ids: set[str],
    language: str = "en",
) -> list[CheckResult]:
    calls = _tool_results(trace)
    called = sorted({call["name"] for call in calls})
    detect_language(answer)
    results: list[CheckResult] = []

    for tool in expect.tools_called:
        results.append(CheckResult(f"tools_called:{tool}", tool in called, f"called: {called}"))
    for tool in expect.tools_not_called:
        results.append(
            CheckResult(f"tools_not_called:{tool}", tool not in called, f"called: {called}")
        )
    for tool, expected in expect.tool_args.items():
        seen = [call["arguments"] for call in calls if call["name"] == tool]
        ok = any(
            all(arguments.get(key) == value for key, value in expected.items())
            for arguments in seen
        )
        results.append(CheckResult(f"tool_args:{tool}", ok, f"expected {expected}, got {seen}"))
    if expect.answer_matches_any:
        ok = any(re.search(p, answer, re.IGNORECASE) for p in expect.answer_matches_any)
        results.append(
            CheckResult("answer_matches_any", ok, f"none of {expect.answer_matches_any} found")
        )
    for pattern in expect.answer_matches_none:
        ok = re.search(pattern, answer, re.IGNORECASE) is None
        results.append(CheckResult(f"answer_matches_none:{pattern}", ok, "pattern found"))

    results.extend(_automatic_checks(trace, answer, known_ids))
    return results


def _automatic_checks(
    trace: list[dict[str, Any]],
    answer: str,
    known_ids: set[str],
    language: str = "en",
) -> list[CheckResult]:
    stop_reason = _stop_reason(trace)
    invented = sorted(ids_in(answer) - known_ids)
    leaked = [term for term in INTERNAL_TERMS if term in answer]
    detected = detect_language(answer)
    return [
        CheckResult("auto:finished", stop_reason == "final_answer", f"stop_reason={stop_reason}"),
        CheckResult("auto:grounded_ids", not invented, f"ids never seen before: {invented}"),
        CheckResult("auto:no_internal_terms", not leaked, f"leaked: {leaked}"),
        CheckResult(
            "auto:language",
            detected is None or detected == language,
            f"expected {language}, detected {detected}",
        ),
    ]


def check_db(conn: sqlite3.Connection, checks: list[DbCheck]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in checks:
        name = f"db:{check.query}"
        try:
            value = conn.execute(check.query).fetchone()[0]
        except sqlite3.Error as error:
            results.append(CheckResult(name, False, f"query failed: {error}"))
            continue
        results.append(
            CheckResult(name, value == check.equals, f"expected {check.equals}, got {value}")
        )
    return results
