from dataclasses import dataclass
from typing import Literal

from nimbus.agent.llm import LLM
from nimbus.agent.tools import McpTools
from nimbus.agent.types import Message

StopReason = Literal["final_answer", "max_steps"]

FALLBACK_ANSWER = (
    "Sorry, I could not finish handling your request. "
    "I can hand this conversation over to a human agent."
)


@dataclass(frozen=True)
class AgentResult:
    answer: str
    messages: list[Message]
    stop_reason: StopReason
    steps: int


async def run_turn(
    *,
    llm: LLM,
    tools: McpTools,
    system_prompt: str,
    history: list[Message],
    user_text: str,
    max_steps: int = 6,
) -> AgentResult:
    specs = await tools.specs()
    messages = [
        Message(role="system", content=system_prompt),
        *history,
        Message(role="user", content=user_text),
    ]

    for step in range(1, max_steps + 1):
        response = await llm.complete(messages, specs)
        messages.append(
            Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )
        if not response.tool_calls:
            return AgentResult(response.text, messages, "final_answer", step)

        for call in response.tool_calls:
            text, is_error = await tools.call(call.name, call.arguments)
            messages.append(
                Message(role="tool", content=text, tool_call_id=call.id, is_error=is_error)
            )

    return AgentResult(FALLBACK_ANSWER, messages, "max_steps", max_steps)
