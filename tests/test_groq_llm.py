import json
from types import SimpleNamespace

from nimbus.agent.groq_llm import from_groq_message, to_groq_messages, to_groq_tools
from nimbus.agent.types import Message, ToolCall, ToolSpec


def groq_message(content=None, tool_calls=None, reasoning=None):
    """Imitates the shape of the SDK's response message"""
    return SimpleNamespace(content=content, tool_calls=tool_calls, reasoning=reasoning)


def groq_tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments)
    )


def test_tools_use_function_format():
    spec = ToolSpec(name="get_transaction", description="Look up.", input_schema={"type": "object"})
    assert to_groq_tools([spec]) == [
        {
            "type": "function",
            "function": {
                "name": "get_transaction",
                "description": "Look up.",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_assistant_tool_call_sent_with_json_arguments():
    message = Message(
        role="assistant",
        tool_calls=(
            ToolCall(id="c1", name="get_transaction", arguments={"transaction_id": "tx_1"}),
        ),
    )
    [converted] = to_groq_messages([message])
    call = converted["tool_calls"][0]
    assert call["id"] == "c1"
    assert call["function"]["name"] == "get_transaction"
    assert json.loads(call["function"]["arguments"]) == {"transaction_id": "tx_1"}


def test_plain_messages_have_no_tool_calls_key():
    converted = to_groq_messages([Message(role="user", content="hi")])
    assert converted == [{"role": "user", "content": "hi"}]


def test_tool_errors_marked_for_model():
    message = Message(role="tool", content="not found", tool_call_id="c1", is_error=True)
    [converted] = to_groq_messages([message])
    assert converted["role"] == "tool"
    assert converted["tool_call_id"] == "c1"
    assert converted["content"].startswith("ERROR:")


def test_response_with_tool_call_is_parsed():
    response = from_groq_message(
        groq_message(
            tool_calls=[groq_tool_call("c1", "get_transaction", '{"transaction_id": "tx_1"}')],
            reasoning="The customer asks about a withdrawal.",
        )
    )
    assert response.text == ""
    assert response.reasoning == "The customer asks about a withdrawal."
    assert response.tool_calls[0].arguments == {"transaction_id": "tx_1"}


def test_invalid_json_arguments_become_empty_dict():
    response = from_groq_message(
        groq_message(tool_calls=[groq_tool_call("c1", "get_transaction", "{not json")])
    )
    assert response.tool_calls[0].arguments == {}
