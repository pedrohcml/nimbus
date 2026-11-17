import pytest

from nimbus.agent.llm import ScriptedLLM
from nimbus.agent.types import LLMResponse, ToolCall
from nimbus.backend.seed import TX_DUPLICATE_B, TX_WITHDRAWAL_CONFIRMING
from nimbus.evals.dataset import DbCheck, EvalCase, Turn, TurnExpect
from nimbus.evals.runner import run_case, run_suite

pytestmark = pytest.mark.anyio


def say(text):
    return LLMResponse(text=text)


def use(name, **arguments):
    return LLMResponse(tool_calls=(ToolCall(id="c1", name=name, arguments=arguments),))


def case(*turns, **fields):
    return EvalCase(id="case", category="lookup", turns=list(turns), **fields)


LOOKUP = Turn(
    user=f"Status from {TX_WITHDRAWAL_CONFIRMING}?",
    expect=TurnExpect(tools_called=["get_transaction"]),
)


async def test_passing_run():
    def script():
        return ScriptedLLM(
            [use("get_transaction", transaction_id=TX_WITHDRAWAL_CONFIRMING), say("Confirming.")]
        )

    result = await run_case(case(LOOKUP), script)
    assert result.status == "passed"


async def test_failing_run_reports_failed_check():
    result = await run_case(case(LOOKUP), lambda: ScriptedLLM([say("I don't know.")]))
    assert result.status == "failed"
    assert "tools_called:get_transaction" in {c.name for c in result.failed_checks}


async def test_each_run_gets_fresh_database():
    dispute = case(
        Turn(
            user=f"Open dispute for {TX_DUPLICATE_B}",
            expect=TurnExpect(tools_called=["open_dispute"]),
        ),
        db=[DbCheck(query="select count(*) from disputes", equals=1)],
    )

    def script():
        return ScriptedLLM(
            [
                use("open_dispute", transaction_id=TX_DUPLICATE_B, reason_code="duplicate"),
                say("Open."),
            ]
        )

    results = await run_suite([dispute], script, runs=2)
    assert [r.status for r in results] == ["passed", "passed"]


async def test_history_passed_between_turns():
    created = []

    def factory():
        llm = ScriptedLLM([say("Hello! What's the ID?"), say("Ok.")])
        created.append(llm)
        return llm

    two_turns = case(Turn(user="Where is my charge?"), Turn(user="I don't know the ID"))
    await run_case(two_turns, factory)
    second_call = created[0].calls[1]
    assert any(m.role == "user" and m.content == "Where is my charge?" for m in second_call)


async def test_approval_threshold_from_case_is_used():
    refund = case(
        Turn(user=f"Total refind of {TX_DUPLICATE_B}"),
        approval_threshold_minor=10_000,
        db=[
            DbCheck(
                query="select count(*) from refund_requests where status = 'pending_approval'",
                equals=1,
            )
        ],
    )

    def script():
        return ScriptedLLM(
            [
                use("request_refund", transaction_id=TX_DUPLICATE_B, amount_minor=34_900),
                say("In analysis."),
            ]
        )

    assert (await run_case(refund, script)).status == "passed"


async def test_provider_failure_is_error_not_failure():
    class BrokenLLM:
        async def complete(self, messages, tools):
            raise RuntimeError("rate limit exceeded")

    result = await run_case(case(LOOKUP), BrokenLLM)
    assert result.status == "error"
    assert "rate limit exceeded" in result.error
