import pytest

from nimbus.agent.graph import build_agent_graph, run_graph_turn
from nimbus.agent.llm import ScriptedLLM
from nimbus.agent.loop import FALLBACK_ANSWER
from nimbus.agent.tools import McpTools
from nimbus.agent.types import (
    LLMResponse,
    Message,
    ToolCall,
    message_from_dict,
    message_to_dict,
)
from nimbus.backend.seed import TX_WITHDRAWAL_CONFIRMING

pytestmark = pytest.mark.anyio


def say(text):
    return LLMResponse(text=text)


def use(*calls):
    return LLMResponse(tool_calls=calls)


def call(name, call_id="c1", **arguments):
    return ToolCall(id=call_id, name=name, arguments=arguments)


async def build(llm, client, max_steps=6):
    return await build_agent_graph(
        llm=llm, tools=McpTools(client), system_prompt=lambda: "sys", max_steps=max_steps
    )


def test_message_round_trip():
    message = Message(
        role="assistant", tool_calls=(ToolCall(id="c1", name="x", arguments={"a": 1}),)
    )
    assert message_from_dict(message_to_dict(message)) == message


async def test_answers_directly(client):
    graph = await build(ScriptedLLM([say("Hello!")]), client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    assert result.answer == "Hello!"
    assert result.stop_reason == "final_answer"
    assert result.steps == 1


async def test_calls_tool_feeds_result_back(client):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id=TX_WITHDRAWAL_CONFIRMING)), say("2 of 3.")]
    )
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="status?")
    tool_message = llm.calls[1][-1]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "c1"
    assert "confirming" in tool_message.content
    assert result.steps == 2


async def test_system_prompt_sent_but_not_stored(client):
    llm = ScriptedLLM([say("ok")])
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    assert llm.calls[0][0].role == "system"
    assert all(message.role != "system" for message in result.messages)


async def test_stops_at_max_steps(client):
    again = use(call("get_transaction", transaction_id=TX_WITHDRAWAL_CONFIRMING))
    llm = ScriptedLLM([again, again])
    graph = await build(llm, client, max_steps=2)
    result = await run_graph_turn(graph, thread_id="t1", user_text="status?")
    assert result.stop_reason == "max_steps"
    assert result.answer == FALLBACK_ANSWER
    assert len(llm.calls) == 2


async def test_trace_records_turn_in_order(client):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id=TX_WITHDRAWAL_CONFIRMING)), say("Done.")]
    )
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="status?")
    assert [event["type"] for event in result.trace] == [
        "turn_start",
        "llm_response",
        "tool_result",
        "llm_response",
        "turn_end",
    ]


async def test_conversation_is_remembered_per_thread(client):
    llm = ScriptedLLM([say("what is the id?"), say("Thanks.")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="where is my withdrawal?")
    await run_graph_turn(graph, thread_id="t1", user_text="I don't know the ID")
    second_call = llm.calls[1]
    assert any(m.role == "user" and m.content == "where is my withdrawal?" for m in second_call)


async def test_threads_are_isolated(client):
    llm = ScriptedLLM([say("a"), say("b")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="first")
    await run_graph_turn(graph, thread_id="t2", user_text="second")
    assert not any(message.content == "first" for message in llm.calls[1])


async def test_each_turn_returns_onlt_its_own_trace(client):
    llm = ScriptedLLM([say("a"), say("b")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="first")
    second = await run_graph_turn(graph, thread_id="t1", user_text="second")
    assert [event["type"] for event in second.trace] == ["turn_start", "llm_response", "turn_end"]
