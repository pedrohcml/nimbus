import json
import logging
from typing import Any

from groq import AsyncGroq

from nimbus.agent.types import LLMResponse, Message, ToolCall, ToolSpec

logger = logging.getLogger(__name__)


def to_groq_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema,
            },
        }
        for spec in specs
    ]


def to_groq_messages(messages: list[Message]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            content = f"ERROR: {message.content}" if message.is_error else message.content
            converted.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": content}
            )
        elif message.tool_calls:
            converted.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        else:
            converted.append({"role": message.role, "content": message.content})
    return converted


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        logger.warning("model sent invalid JSON arguments: %r", raw)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def from_groq_message(message: Any) -> LLMResponse:
    tool_calls = tuple(
        ToolCall(
            id=call.id,
            name=call.function.name,
            arguments=_parse_arguments(call.function.arguments),
        )
        for call in (message.tool_calls or [])
    )
    return LLMResponse(
        text=message.content or "",
        tool_calls=tool_calls,
        reasoning=getattr(message, "reasoning", None) or "",
    )


class GroqLLM:
    """LLM adapter for Groq's chat completions API"""

    def __init__(self, client: AsyncGroq, model: str, reasoning_effort: str = "medium") -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort

    async def complete(self, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=to_groq_messages(messages),
            tools=to_groq_tools(tools),
            tool_choice="auto",
            reasoning_effort=self._reasoning_effort,
        )
        return from_groq_message(response.choices[0].message)
