from typing import Protocol

from nimbus.agent.types import LLMResponse, Message, ToolSpec


class LLM(Protocol):
    async def complete(self, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse: ...


class ScriptedLLM:
    """Test double: returns pre-written responses in order and records its inputs."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Message]] = []
        self.tools_seen: list[list[ToolSpec]] = []

    async def complete(self, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        self.calls.append(list(messages))
        self.tools_seen.append(list(tools))
        if not self._responses:
            raise AssertionError("ScriptedLLM ran out if responses")
        return self._responses.pop(0)
