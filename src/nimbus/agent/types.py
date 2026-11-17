from dataclasses import asdict, dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """Model asking to run one tool"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    is_error: bool = False


@dataclass(frozen=True)
class ToolSpec:
    "What the model sees about a tool"

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning: str = ""


def message_to_dict(message: Message) -> dict[str, Any]:
    return {**asdict(message), "tool_calls": [asdict(call) for call in message.tool_calls]}


def message_from_dict(data: dict[str, Any]) -> Message:
    return Message(
        role=data["role"],
        content=data["content"],
        tool_calls=tuple(ToolCall(**call) for call in data["tool_calls"]),
        tool_call_id=data["tool_call_id"],
        is_error=data["is_error"],
    )
