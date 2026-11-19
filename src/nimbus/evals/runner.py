from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from anyio import sleep
from mcp import Client

from nimbus.agent.graph import build_agent_graph, run_graph_turn
from nimbus.agent.llm import LLM
from nimbus.agent.prompts import build_system_prompt
from nimbus.agent.tools import McpTools
from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import BASE_TIME, seed_db
from nimbus.evals.checks import CheckResult, check_db, check_turn, ids_in
from nimbus.evals.dataset import EvalCase
from nimbus.mcp_server.server import build_server
from nimbus.mcp_server.session import Session
from nimbus.rag.retrieval import Retriever

EVAL_NOW = BASE_TIME

Status = Literal["passed", "failed", "error"]


@dataclass
class TurnResult:
    user: str
    answer: str
    checks: list[CheckResult]
    trace: list[dict[str, Any]]


@dataclass
class RunResult:
    case_id: str
    run_index: int
    turns: list[TurnResult] = field(default_factory=list)
    db_checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def checks(self) -> list[CheckResult]:
        return [check for turn in self.turns for check in turn.checks] + self.db_checks

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]

    @property
    def status(self) -> Status:
        if self.error is not None:
            return "error"
        return "passed" if not self.failed_checks else "failed"


def _describe(error: BaseException) -> str:
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return f"{type(error).__name__}: {error}"


async def run_case(
    case: EvalCase,
    make_llm: Callable[[], LLM],
    *,
    run_index: int = 0,
    now: datetime = EVAL_NOW,
    seed: int = 42,
    retriever: Retriever | None = None,
) -> RunResult:
    result = RunResult(case_id=case.id, run_index=run_index)
    llm = make_llm()

    conn = connect_db(":memory:")
    init_db(conn)
    seed_db(conn, seed=seed)
    session = Session(
        conn=conn,
        customer_id=case.customer,
        conversation_id=f"eval-{case.id}-{run_index}",
        clock=lambda: now,
    )
    options = (
        {}
        if case.approval_threshold_minor is None
        else {"refund_approval_threshold_minor": case.approval_threshold_minor}
    )

    try:
        async with Client(build_server(lambda: session, retriever=retriever, **options)) as client:
            graph = await build_agent_graph(
                llm=llm,
                tools=McpTools(client),
                system_prompt=lambda: build_system_prompt(now),
            )
            known_ids: set[str] = set()

            for turn in case.turns:
                known_ids |= ids_in(turn.user)
                agent = await run_graph_turn(
                    graph, thread_id=session.conversation_id, user_text=turn.user
                )
                for event in agent.trace:
                    if event["type"] == "tool_result":
                        known_ids |= ids_in(event["content"])
                result.turns.append(
                    TurnResult(
                        user=turn.user,
                        answer=agent.answer,
                        checks=check_turn(
                            turn.expect,
                            agent.trace,
                            agent.answer,
                            known_ids,
                            turn.language or case.language,
                        ),
                        trace=agent.trace,
                    )
                )

            result.db_checks = check_db(conn, case.db)
    except Exception as error:
        result.error = _describe(error)
    return result


async def run_suite(
    cases: list[EvalCase],
    make_llm: Callable[[], LLM],
    *,
    runs: int = 3,
    pause_s: float = 0.0,
    max_consecutive_errors: int = 3,
    on_result: Callable[[RunResult], None] | None = None,
    retriever: Retriever | None = None,
) -> list[RunResult]:
    results: list[RunResult] = []
    consecutive_errors = 0
    for case in cases:
        for run_index in range(runs):
            if results and pause_s:
                await sleep(pause_s)
            result = await run_case(case, make_llm, run_index=run_index, retriever=retriever)
            results.append(result)
            if on_result is not None:
                on_result(result)
            consecutive_errors = consecutive_errors + 1 if result.status == "error" else 0
            if consecutive_errors >= max_consecutive_errors:
                return results
    return results
