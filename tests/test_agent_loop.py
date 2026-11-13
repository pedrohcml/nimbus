import pytest

from nimbus.agent.llm import ScriptedLLM
from nimbus.agent.loop import run_turn
from nimbus.agent.tools import McpTools
from nimbus.agent.types import LLMResponse, ToolCall

pytestmark = pytest.mark.anyio


@pytest.fixture
def tools(client):
    return McpTools(client)


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
