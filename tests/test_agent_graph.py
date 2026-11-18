import json

import pytest

from nimbus.agent.confirmation import format_amount, is_confirmation, is_rejection
from nimbus.agent.graph import FALLBACK_ANSWER, build_agent_graph, run_graph_turn
from nimbus.agent.llm import ScriptedLLM
from nimbus.agent.tools import McpTools
from nimbus.agent.types import (
    LLMResponse,
    Message,
    ToolCall,
    message_from_dict,
    message_to_dict,
)
from nimbus.backend.seed import (
    TX_DUPLICATE_A,
    TX_DUPLICATE_B,
    TX_OTHER_CUSTOMER,
    TX_WITHDRAWAL_CONFIRMING,
)

pytestmark = pytest.mark.anyio


class FlakyLLM:
    def __init__(self, responses):
        self.inner = ScriptedLLM(responses)
        self.failed = False

    async def complete(self, messages, tools):
        if not self.failed:
            self.failed = True
            raise RuntimeError("provider down")
        return await self.inner.complete(messages, tools)


class ExplodingTools:
    def __init__(self, inner):
        self._inner = inner

    async def specs(self):
        return await self._inner.specs()

    async def call(self, name, arguments):
        raise RuntimeError("connection to /var/run/mcp.sock lost")


def say(text):
    return LLMResponse(text=text)


def use(*calls):
    return LLMResponse(tool_calls=calls)


def call(name, call_id="c1", **arguments):
    return ToolCall(id=call_id, name=name, arguments=arguments)


def count(conn, table):
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


async def build(llm, client, max_steps=6, tools=None):
    return await build_agent_graph(
        llm=llm,
        tools=tools or McpTools(client),
        system_prompt=lambda: "sys",
        max_steps=max_steps,
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
    assert result.trace[-1]["stop_reason"] == "max_steps"


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


@pytest.mark.parametrize(
    "reply", ["yes", "Yes, confirmed.", "ok", "Sim", "sim, pode abrir", "Go ahead"]
)
def test_confirmations(reply):
    assert is_confirmation(reply)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [("no", True), ("Não, cancela", True), ("Actually, open a dispute", False)],
)
def test_rejections(reply, expected):
    assert is_rejection(reply) is expected


@pytest.mark.parametrize(
    "reply", ["no", "No, cancel it", "não", "wait, how much?", "yes... actualy no"]
)
def test_not_confirmations(reply):
    assert not is_confirmation(reply)


def test_format_amount():
    assert format_amount(34_900, "BRL", "en") == "R$ 349.00"
    assert format_amount(34_900, "BRL", "pt") == "R$ 349,00"
    assert format_amount(123_456_789, "BRL", "pt") == "R$ 1.234.567,89"
    assert format_amount(20_000, "BTC", "en") == "0.0002 BTC"


REFUND = use(call("request_refund", transaction_id=TX_DUPLICATE_B, amount_minor=10_000))


async def test_refund_waits_for_confirmation(client, session):
    graph = await build(ScriptedLLM([REFUND, say("Done.")]), client)

    first = await run_graph_turn(
        graph, thread_id="t1", user_text="Refund R$ 100 of the second charge"
    )
    assert first.stop_reason == "needs_confirmation"
    assert "R$ 100.00" in first.answer
    assert TX_DUPLICATE_B in first.answer
    assert count(session.conn, "refund_requests") == 0
    assert [e["type"] for e in first.trace] == ["turn_start", "llm_response", "turn_end"]

    second = await run_graph_turn(graph, thread_id="t1", user_text="Yes, confirmed.")
    assert second.stop_reason == "final_answer"
    assert count(session.conn, "refund_requests") == 1
    assert [e["type"] for e in second.trace] == [
        "turn_start",
        "confirmation",
        "tool_result",
        "llm_response",
        "turn_end",
    ]

    timestamps = [e["ts"] for e in second.trace]
    assert timestamps == sorted(timestamps)
    assert second.trace[0]["step"] == second.trace[1]["step"]


async def test_declined_action_is_not_executed(client, session):
    llm = ScriptedLLM([REFUND, say("Ok, cancelled.")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="Refund R$ 100 of the second charge")
    await run_graph_turn(graph, thread_id="t1", user_text="No, cancel it")
    assert count(session.conn, "refund_requests") == 0
    sent = llm.calls[1]
    assert sent[-2].role == "tool" and sent[-2].is_error
    assert "cancelled" in sent[-2].content
    assert sent[-1].role == "user" and sent[-1].content == "No, cancel it"


async def test_confirmation_question_follows_customer_language(client):
    graph = await build(ScriptedLLM([REFUND]), client)
    result = await run_graph_turn(
        graph,
        thread_id="t1",
        user_text="Quero reembolso de R$ 100 da segunda cobrança, você pode fazer?",
    )
    assert "R$ 100,00" in result.answer
    assert "sim" in result.answer


async def test_model_receives_user_message_and_tools(client):
    llm = ScriptedLLM([say("ok")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="hi")
    assert llm.calls[0][-1].content == "hi"
    assert "get_transaction" in {spec.name for spec in llm.tools_seen[0]}


async def test_tool_error_fed_back_and_marked_in_trace(client):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id=TX_OTHER_CUSTOMER)), say("Not found.")]
    )
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    tool_message = llm.calls[1][-1]
    assert tool_message.is_error
    assert "not found" in tool_message.content
    assert result.stop_reason == "final_answer"
    tool_event = next(e for e in result.trace if e["type"] == "tool_result")
    assert tool_event["is_error"] is True


async def test_unknown_tool_reported_without_calling_server(client):
    llm = ScriptedLLM([use(call("delete_account")), say("I can't do that.")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="hi")
    tool_message = llm.calls[1][-1]
    assert tool_message.is_error
    assert "delete_account" in tool_message.content
    assert "get_transaction" in tool_message.content


async def test_crashing_tool_doesnt_leak_internal_details(client):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id=TX_WITHDRAWAL_CONFIRMING)), say("Sorry.")]
    )
    graph = await build(llm, client, tools=ExplodingTools(McpTools(client)))
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    tool_message = llm.calls[1][-1]
    assert tool_message.is_error
    assert "mcp.sock" not in tool_message.content
    assert result.stop_reason == "final_answer"


async def test_multiple_tool_calls_run_in_order(client):
    llm = ScriptedLLM(
        [
            use(
                call("get_transaction", "c1", transaction_id=TX_DUPLICATE_A),
                call("get_transaction", "c2", transaction_id=TX_DUPLICATE_B),
            ),
            say("You were charged twice."),
        ]
    )
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    tool_messages = [m for m in llm.calls[1] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["c1", "c2"]
    assert result.steps == 2


async def test_trace_is_json_serializable(client):
    llm = ScriptedLLM(
        [use(call("get_transaction", transaction_id=TX_WITHDRAWAL_CONFIRMING)), say("Done.")]
    )
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    json.dumps(result.trace)


async def test_trace_keeps_model_reasoning(client):
    llm = ScriptedLLM([LLMResponse(text="Hi!", reasoning="Greeting, no tool needed.")])
    graph = await build(llm, client)
    result = await run_graph_turn(graph, thread_id="t1", user_text="hi")
    event = next(e for e in result.trace if e["type"] == "llm_response")
    assert event["reasoning"] == "Greeting, no tool needed."
    assert "no tool needed" not in result.answer


async def test_turn_after_provider_failure_starts_fresh(client):
    llm = FlakyLLM([say("Hello!")])
    graph = await build(llm, client)
    with pytest.raises(RuntimeError):
        await run_graph_turn(graph, thread_id="t1", user_text="hi")

    result = await run_graph_turn(graph, thread_id="t1", user_text="hi again")
    assert result.stop_reason == "final_answer"
    assert llm.inner.calls[0][-1].content == "hi again"


async def test_reply_not_confirmation_reaches_model(client, session):
    llm = ScriptedLLM([REFUND, say("Sure, which transaction?")])
    graph = await build(llm, client)
    await run_graph_turn(graph, thread_id="t1", user_text="Refund R$ 100 of the second charge")
    await run_graph_turn(graph, thread_id="t1", user_text="Actually, open a dispute instead")
    last = llm.calls[1][-1]
    assert last.role == "user"
    assert last.content == "Actually, open a dispute instead"
    assert count(session.conn, "refund_requests") == 0
    tool_message = llm.calls[1][-2]
    assert "Not executed" in tool_message.content
    assert "cancelled" not in tool_message.content
