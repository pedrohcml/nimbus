import json
from types import SimpleNamespace

import pytest

from nimbus.agent.ollama_llm import (
    OllamaLLM,
    from_chat_message,
    ollama_client,
    to_chat_messages,
    to_chat_tools,
)
from nimbus.agent.types import Message, ToolCall, ToolSpec


def chat_message(content=None, tool_calls=None, reasoning=None):
    """Imitates the shape of the SDK's response message"""
    return SimpleNamespace(content=content, tool_calls=tool_calls, reasoning=reasoning)


def chat_tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id, type="function", function=SimpleNamespace(name=name, arguments=arguments)
    )


def test_tools_use_function_format():
    spec = ToolSpec(name="get_transaction", description="Look up.", input_schema={"type": "object"})
    assert to_chat_tools([spec]) == [
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
    [converted] = to_chat_messages([message])
    call = converted["tool_calls"][0]
    assert call["id"] == "c1"
    assert call["function"]["name"] == "get_transaction"
    assert json.loads(call["function"]["arguments"]) == {"transaction_id": "tx_1"}


def test_plain_messages_have_no_tool_calls_key():
    converted = to_chat_messages([Message(role="user", content="hi")])
    assert converted == [{"role": "user", "content": "hi"}]


def test_tool_errors_marked_for_model():
    message = Message(role="tool", content="not found", tool_call_id="c1", is_error=True)
    [converted] = to_chat_messages([message])
    assert converted["role"] == "tool"
    assert converted["tool_call_id"] == "c1"
    assert converted["content"].startswith("ERROR:")


def test_response_with_tool_call_is_parsed():
    response = from_chat_message(
        chat_message(
            tool_calls=[chat_tool_call("c1", "get_transaction", '{"transaction_id": "tx_1"}')],
            reasoning="The customer asks about a withdrawal.",
        )
    )
    assert response.text == ""
    assert response.reasoning == "The customer asks about a withdrawal."
    assert response.tool_calls[0].arguments == {"transaction_id": "tx_1"}


def test_invalid_json_arguments_become_empty_dict():
    response = from_chat_message(
        chat_message(tool_calls=[chat_tool_call("c1", "get_transaction", "{not json")])
    )
    assert response.tool_calls[0].arguments == {}


class FakeChatClient:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=chat_message(content="ok"))])


HI = [Message(role="user", content="hi")]


@pytest.mark.anyio
async def test_sampling_parameters_reach_request():
    client = FakeChatClient()
    await OllamaLLM(client, "model", temperature=0.6, seed=7).complete(HI, [])
    sent = client.calls[0]
    assert sent["temperature"] == 0.6
    assert sent["seed"] == 7
    assert "top_p" not in sent


@pytest.mark.anyio
async def test_no_sampling_parameters_by_default():
    client = FakeChatClient()
    await OllamaLLM(client, "model").complete(HI, [])
    sent = client.calls[0]
    assert "temperature" not in sent
    assert "seed" not in sent
    assert "top_p" not in sent


@pytest.mark.anyio
async def test_request_keeps_tool_choice_and_reasoning_effort():
    client = FakeChatClient()
    response = await OllamaLLM(client, "model", "low").complete(HI, [])
    sent = client.calls[0]
    assert sent["tool_choice"] == "auto"
    assert sent["reasoning_effort"] == "low"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert response.text == "ok"


def test_client_points_to_local_server(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert str(ollama_client().base_url).startswith("http://localhost:11434/v1")
