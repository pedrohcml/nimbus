import logging
import operator
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from nimbus.agent.confirmation import (
    SENSITIVE_TOOLS,
    confirmation_question,
    is_confirmation,
    is_rejection,
)
from nimbus.agent.language import conversation_language
from nimbus.agent.llm import LLM
from nimbus.agent.tools import Tools
from nimbus.agent.types import Message, ToolCall, message_from_dict, message_to_dict

StopReason = Literal["final_answer", "max_steps", "needs_verification"]

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = (
    "Sorry, I could not finish handling your request. "
    "I can hand this conversation over to a human agent."
)

CANCELLED = (
    "Cancelled: the customer said no when the system asked them to confirm, "
    "so this action was not executed. Tell them it was cancelled. "
    "Do not ask again and do not call it again unless they ask for it again."
)
NOT_CONFIRMED = (
    "Not executed: the customer replied without confirming. Their reply is the "
    "next message: answer it. Call this action again only if they ask for it."
)


@dataclass(frozen=True)
class AgentResult:
    answer: str
    messages: list[Message]
    stop_reason: StopReason
    steps: int
    trace: list[dict[str, Any]]


class AgentState(TypedDict):
    messages: Annotated[list[dict[str, Any]], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    turn_id: str
    steps: int
    approved: bool | None
    confirmation_reply: str


async def build_agent_graph(
    *,
    llm: LLM,
    tools: Tools,
    system_prompt: Callable[[], str],
    max_steps: int = 6,
    checkpointer: BaseCheckpointSaver | None = None,
):
    specs = await tools.specs()
    tool_names = {spec.name for spec in specs}

    async def agent(state: AgentState) -> dict[str, Any]:
        step = state["steps"] + 1
        messages = [Message(role="system", content=system_prompt())]
        messages += [message_from_dict(m) for m in state["messages"]]
        started = time.perf_counter()
        response = await llm.complete(messages, specs)
        reply = Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
        event = _event(
            state["turn_id"],
            step,
            "llm_response",
            text=response.text,
            reasoning=response.reasoning,
            tool_calls=[asdict(c) for c in response.tool_calls],
            elapsed_ms=_elapsed_ms(started),
        )
        return {"messages": [message_to_dict(reply)], "trace": [event], "steps": step}

    async def run_tools(state: AgentState) -> dict[str, Any]:
        last = message_from_dict(state["messages"][-1])
        new_messages, events = [], []
        declined = False
        for tool_call in last.tool_calls:
            started = time.perf_counter()
            if tool_call.name in SENSITIVE_TOOLS and not state.get("approved"):
                reply_text = state.get("confirmation_reply", "")
                text = CANCELLED if is_rejection(reply_text) else NOT_CONFIRMED
                is_error = True
                declined = True
            else:
                text, is_error = await _execute(tools, tool_names, tool_call)
            events.append(
                _event(
                    state["turn_id"],
                    state["steps"],
                    "tool_result",
                    call_id=tool_call.id,
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                    is_error=is_error,
                    content=text,
                    elapsed_ms=_elapsed_ms(started),
                )
            )
            reply = Message(role="tool", content=text, tool_call_id=tool_call.id, is_error=is_error)
            new_messages.append(message_to_dict(reply))
        if declined and state.get("confirmation_reply"):
            customer = Message(role="user", content=state["confirmation_reply"])
            new_messages.append(message_to_dict(customer))
        return {
            "messages": new_messages,
            "trace": events,
            "approved": None,
            "confirmation_reply": "",
        }

    async def confirm(state: AgentState) -> dict[str, Any]:
        last = message_from_dict(state["messages"][-1])
        sensitive = [c for c in last.tool_calls if c.name in SENSITIVE_TOOLS]
        user_texts = [m["content"] for m in state["messages"] if m["role"] == "user"]
        language = conversation_language(user_texts)
        question = await confirmation_question(sensitive, tools, language)

        reply = interrupt({"question": question})

        approved = is_confirmation(reply)
        event = _event(
            state["turn_id"],
            state["steps"],
            "confirmation",
            question=question,
            reply=reply,
            approved=approved,
        )
        return {"approved": approved, "confirmation_reply": reply, "trace": [event]}

    def finish(state: AgentState) -> dict[str, Any]:
        answer = state["messages"][-1]["content"]
        event = _event(
            state["turn_id"],
            state["steps"],
            "turn_end",
            stop_reason="final_answer",
            steps=state["steps"],
            answer=answer,
        )
        return {"trace": [event]}

    def give_up(state: AgentState) -> dict[str, Any]:
        reply = Message(role="assistant", content=FALLBACK_ANSWER)
        event = _event(
            state["turn_id"],
            state["steps"],
            "turn_end",
            stop_reason="max_steps",
            steps=state["steps"],
            answer=FALLBACK_ANSWER,
        )
        return {"messages": [message_to_dict(reply)], "trace": [event]}

    def after_agent(state: AgentState) -> str:
        calls = state["messages"][-1]["tool_calls"]
        if not calls:
            return "finish"
        if any(call["name"] in SENSITIVE_TOOLS for call in calls):
            return "confirm"
        return "tools"

    def after_tools(state: AgentState) -> str:
        return "give_up" if state["steps"] >= max_steps else "agent"

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_node("tools", run_tools)
    builder.add_node("finish", finish)
    builder.add_node("give_up", give_up)
    builder.add_node("confirm", confirm)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", after_agent, {"tools": "tools", "confirm": "confirm", "finish": "finish"}
    )
    builder.add_conditional_edges("tools", after_tools, {"agent": "agent", "give_up": "give_up"})
    builder.add_edge("finish", END)
    builder.add_edge("give_up", END)
    builder.add_edge("confirm", "tools")
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


async def run_graph_turn(graph, *, thread_id: str, user_text: str) -> AgentResult:

    config = {"configurable": {"thread_id": thread_id}}
    user = Message(role="user", content=user_text)
    snapshot = await graph.aget_state(config)
    paused = any(task.interrupts for task in snapshot.tasks)

    if paused:
        turn_id = snapshot.values["turn_id"]
        before = len(snapshot.values["trace"])
        start = _event(
            turn_id, snapshot.values["steps"], "turn_start", user_text=user_text, resumed=True
        )
        state = await graph.ainvoke(Command(resume=user_text), config)
        trace = [start] + state["trace"][before:]
    else:
        turn_id = uuid.uuid4().hex[:12]
        user = Message(role="user", content=user_text)
        state = await graph.ainvoke(
            {
                "messages": [message_to_dict(user)],
                "trace": [_event(turn_id, 0, "turn_start", user_text=user_text)],
                "turn_id": turn_id,
                "steps": 0,
                "approved": None,
                "confirmation_reply": "",
            },
            config,
        )
        trace = [event for event in state["trace"] if event["turn_id"] == turn_id]

    messages = [message_from_dict(m) for m in state["messages"]]
    if "__interrupt__" in state:
        question = state["__interrupt__"][0].value["question"]
        end = _event(
            turn_id,
            state["steps"],
            "turn_end",
            stop_reason="needs_confirmation",
            steps=state["steps"],
            answer=question,
        )
        return AgentResult(question, messages, "needs_confirmation", state["steps"], trace + [end])

    end = trace[-1]
    return AgentResult(end["answer"], messages, end["stop_reason"], end["steps"], trace)


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
