import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from nimbus.agent.llm import LLM
from nimbus.agent.tools import Tools
from nimbus.agent.types import Message, ToolCall

StopReason = Literal["final_answer", "max_steps"]

logger = logging.getLogger(__name__)

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
    trace: list[dict[str, Any]]


async def run_turn(
    *,
    llm: LLM,
    tools: Tools,
    system_prompt: str,
    history: list[Message],
    user_text: str,
    max_steps: int = 6,
) -> AgentResult:
    specs = await tools.specs()
    tool_names = {spec.name for spec in specs}
    turn_id = uuid.uuid4().hex[:12]
    trace = [
        _event(
            turn_id,
            0,
            "turn_start",
            user_text=user_text,
            tools=sorted(tool_names),
            max_steps=max_steps,
        )
    ]
    messages = [
        Message(role="system", content=system_prompt),
        *history,
        Message(role="user", content=user_text),
    ]

    def finish(answer: str, stop_reason: StopReason, steps: int) -> AgentResult:
        trace.append(
            _event(turn_id, steps, "turn_end", stop_reason=stop_reason, steps=steps, answer=answer)
        )
        return AgentResult(answer, messages, stop_reason, steps, trace)

    for step in range(1, max_steps + 1):
        started = time.perf_counter()
        response = await llm.complete(messages, specs)
        trace.append(
            _event(
                turn_id,
                step,
                "llm_response",
                text=response.text,
                tool_calls=[asdict(c) for c in response.tool_calls],
                elapsed_ms=_elapsed_ms(started),
            )
        )
        messages.append(
            Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        )
        if not response.tool_calls:
            return finish(response.text, "final_answer", step)

        for call in response.tool_calls:
            started = time.perf_counter()
            text, is_error = await _execute(tools, tool_names, call)
            trace.append(
                _event(
                    turn_id,
                    step,
                    "tool_result",
                    call_id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                    is_error=is_error,
                    content=text,
                    elapsed_ms=_elapsed_ms(started),
                )
            )
            messages.append(
                Message(role="tool", content=text, tool_call_id=call.id, is_error=is_error)
            )

    return finish(FALLBACK_ANSWER, "max_steps", max_steps)


async def _execute(tools: Tools, tool_names: set[str], call: ToolCall) -> tuple[str, bool]:
    if call.name not in tool_names:
        available = ", ".join(sorted(tool_names))
        return f"Unknown tool '{call.name}'. Available tools: {available}.", True
    try:
        return await tools.call(call.name, call.arguments)
    except Exception:
        logger.exception("tool %s failed", call.name)
        return "The tool failed unexpectedly. Do not retry it. Offer to escalate.", True


def _event(turn_id: str, step: int, event_type: str, **data: Any) -> dict[str, Any]:
    return {
        "ts": datetime.now(UTC).isoformat(),
        "turn_id": turn_id,
        "step": step,
        "type": event_type,
        **data,
    }


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
