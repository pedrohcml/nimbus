import json

import pytest

from nimbus.agent.llm import ScriptedLLM
from nimbus.agent.loop import FALLBACK_ANSWER, run_turn
from nimbus.agent.tools import McpTools
from nimbus.agent.types import LLMResponse, ToolCall

pytestmark = pytest.mark.anyio


class ExplodingTools:
    """Toolbox whose calls always crash as if the MCP connection"""

    def __init__(self, inner):
        self._inner = inner

    async def specs(self):
        return await self._inner.specs()

    async def call(self, name, arguments):
        raise RuntimeError("connection to /var/run/mcp.sock lost")


@pytest.fixture
def tools(client):
    return McpTools(client)


def say(text):
    return LLMResponse(text=text)


def use(*calls):
    return LLMResponse(tool_calls=calls)


def call(name, call_id="c1", **arguments):
    return ToolCall(id=call_id, name=name, arguments=arguments)


async def run(llm, tools, **overrides):
    args = {"system_prompt": "sys", "history": [], "user_text": "hi"}
    args.update(overrides)
    return await run_turn(llm=llm, tools=tools, **args)


async def test_answers_directly_without_tools(tools):
    llm = ScriptedLLM([LLMResponse(text="Hello! How can I help?")])
    result = await run_turn(llm=llm, tools=tools, system_prompt="sys", history=[], user_text="hi")
    assert result.answer == "Hello! How can I help?"
    assert result.stop_reason == "final_answer"
    assert result.steps == 1


async def test_model_receives_system_prompt_user_message_and_tools(tools):
    llm = ScriptedLLM([LLMResponse(text="ok")])
    await run_turn(llm=llm, tools=tools, system_prompt="sys", history=[], user_text="hi")
    sent = llm.calls[0]
    assert sent[0].role == "system"
    assert sent[0].content == "sys"
    assert sent[-1].role == "user"
    assert sent[-1].content == "hi"
    assert "get_transaction" in {spec.name for spec in llm.tools_seen[0]}


async def test_calls_tool_and_feeds_result_back(tools):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="get_transaction",
                        arguments={"transaction_id": "tx_withdrawal_confirming"},
                    ),
                )
            ),
            LLMResponse(text="Your withdrawal has 2 of 3 confirmations."),
        ]
    )
    result = await run_turn(llm=llm, tools=tools, system_prompt="sys", history=[], user_text="hi")
    assert result.stop_reason == "final_answer"
    assert result.steps == 2
    tool_message = llm.calls[1][-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "call_1"
    assert "confirming" in tool_message.content
    assert not tool_message.is_error


async def test_tool_error_fed_back_loop_continues(tools):
    llm = ScriptedLLM(
        [
            use(call("get_transaction", transaction_id="tx_belongs_to_ricardo")),
            say("I could not find that transaction."),
        ]
    )
    result = await run(llm, tools)
    tool_message = llm.calls[1][-1]
    assert tool_message.is_error
    assert "not found" in tool_message.content
    assert result.stop_reason == "final_answer"


async def test_unknown_tool_reported_without_calling_server(tools):
    llm = ScriptedLLM([use(call("delete_account")), say("I can't do that.")])
    result = await run(llm, tools)
    tool_message = llm.calls[1][-1]
    assert tool_message.is_error
    assert "delete_account" in tool_message.content
    assert "get_transaction" in tool_message.content
    assert result.stop_reason == "final_answer"


async def test_crashing_tool_does_not_leak_internal_details(tools):
    llm = ScriptedLLM(
        [
            use(call("get_transaction", transaction_id="tx_withdrawal_confirming")),
            say("Something went wrong."),
        ]
    )
    result = await run(llm, ExplodingTools(tools))
    tool_message = llm.calls[1][-1]
    assert tool_message.is_error
    assert "mcp.sock" not in tool_message.content
    assert result.stop_reason == "final_answer"


async def test_multiple_tool_calls_run_in_order(tools):
    llm = ScriptedLLM(
        [
            use(
                call("get_transaction", "c1", transaction_id="tx_duplicate_charge_a"),
                call("get_transaction", "c2", transaction_id="tx_duplicate_charge_b"),
            ),
            say("You were charged twice."),
        ]
    )
    result = await run(llm, tools)
    tool_messages = [m for m in llm.calls[1] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["c1", "c2"]
    assert result.steps == 2


async def test_stops_at_max_steps(tools):
    again = use(call("get_transaction", transaction_id="tx_withdrawal_confirming"))
    llm = ScriptedLLM([again, again])
    result = await run(llm, tools, max_steps=2)
    assert result.stop_reason == "max_steps"
    assert result.answer == FALLBACK_ANSWER
    assert len(llm.calls) == 2


async def test_trace_records_turn_in_order(tools):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id="tx_withdrawal_confirming")), say("Done.")]
    )
    result = await run(llm, tools)
    assert [e["type"] for e in result.trace] == [
        "turn_start",
        "llm_response",
        "tool_result",
        "llm_response",
        "turn_end",
    ]
    assert len({e["turn_id"] for e in result.trace}) == 1
    tool_event = result.trace[2]
    assert tool_event["name"] == "get_transaction"
    assert tool_event["is_error"] is False
    assert result.trace[-1]["stop_reason"] == "final_answer"


async def test_trace_marks_tool_errors(tools):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id="tx_belongs_to_ricardo")), say("Not found.")]
    )
    result = await run(llm, tools)
    tool_event = next(e for e in result.trace if e["type"] == "tool_result")
    assert tool_event["is_error"] is True


async def test_trace_records_max_steps(tools):
    again = use(call("get_transaction", transaction_id="tx_withdrawal_confirming"))
    result = await run(ScriptedLLM([again, again]), tools, max_steps=2)
    assert result.trace[-1]["type"] == "turn_end"
    assert result.trace[-1]["stop_reason"] == "max_steps"


async def test_trace_is_json_serializable(tools):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id="tx_withdrawal_confirming")), say("Done.")]
    )
    result = await run(llm, tools)
    json.dumps(result.trace)
