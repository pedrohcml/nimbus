from types import SimpleNamespace

import pytest

from nimbus.router.intents import Intent
from nimbus.router.llm_router import ROUTER_PROMPT, LLMRouter, RouterError, build_router


class FakeCompletions:
    def __init__(self, content, usage=True):
        self.content = content
        self.usage = usage
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        usage = SimpleNamespace(prompt_tokens=120, completion_tokens=8) if self.usage else None
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def fake_client(content, usage=True):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(content, usage)))


@pytest.mark.anyio
async def test_missing_usage_counts_as_zero_tokens():
    client = fake_client('{"intent": "refund"}', usage=False)

    result = await LLMRouter(client, "randomassmodel").route("refund please")

    assert (result.input_tokens, result.output_tokens) == (0, 0)


@pytest.mark.anyio
async def test_returns_intent_and_token_usage():
    client = fake_client('{"intent": "refund"}')

    result = await LLMRouter(client, "randomassmodel").route("i want my money back")

    assert result.intent is Intent.REFUND
    assert (result.input_tokens, result.output_tokens) == (120, 8)


@pytest.mark.anyio
async def test_sends_prompt_and_message():
    client = fake_client('{"intent": "smalltalk"}')

    await LLMRouter(client, "randomassmodel", reasoning_effort="low").route("oi")

    call = client.chat.completions.calls[0]
    assert call["model"] == "randomassmodel"
    assert call["reasoning_effort"] == "low"
    assert call["messages"] == [
        {"role": "system", "content": ROUTER_PROMPT},
        {"role": "user", "content": "oi"},
    ]


@pytest.mark.anyio
async def test_reasoning_is_off_by_default():
    client = fake_client('{"intent": "smalltalk"}')

    await LLMRouter(client, "randomassmodel").route("hello")

    assert client.chat.completions.calls[0]["reasoning_effort"] == "none"


@pytest.mark.anyio
async def test_asks_for_scrict_schema_with_every_intent():
    client = fake_client('{"intent": "smalltalk"}')

    await LLMRouter(client, "randomassmodel").route("i want to speak with someone")

    response_format = client.chat.completions.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["properties"]["intent"]["enum"] == [intent.value for intent in Intent]
    assert schema["required"] == ["intent"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "content", ['{"intent": "greeting"}', "not json", "", '{"intent": "refund", "x": 1}']
)
@pytest.mark.anyio
async def test_invalid_answers_raise_router_error(content):
    with pytest.raises(RouterError):
        await LLMRouter(fake_client(content), "randomassmodel").route("hello")


def test_build_router_uses_router_settings(monkeypatch):
    monkeypatch.delenv("NIMBUS_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("NIMBUS_ROUTER_REASONING_EFFORT", raising=False)

    router = build_router()

    assert router._model == "gemma4:12b"
    assert router._reasoning_effort == "none"
