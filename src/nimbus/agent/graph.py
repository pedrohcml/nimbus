import operator
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from nimbus.agent.llm import LLM
from nimbus.agent.loop import FALLBACK_ANSWER, AgentResult, _elapsed_ms, _event, _execute
from nimbus.agent.tools import Tools
from nimbus.agent.types import Message, message_from_dict, message_to_dict


class AgentState(TypedDict):
    messages: Annotated[list[dict[str, Any]], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    turn_id: str
    steps: int


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
        for tool_call in last.tool_calls:
            started = time.perf_counter()
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
        return {"messages": new_messages, "trace": events}

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
        return "tools" if state["messages"][-1]["tool_calls"] else "finish"

    def after_tools(state: AgentState) -> str:
        return "give_up" if state["steps"] >= max_steps else "agent"

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_node("tools", run_tools)
    builder.add_node("finish", finish)
    builder.add_node("give_up", give_up)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", after_agent, {"tools": "tools", "finish": "finish"})
    builder.add_conditional_edges("tools", after_tools, {"agent": "agent", "give_up": "give_up"})
    builder.add_edge("finish", END)
    builder.add_edge("give_up", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


async def run_graph_turn(graph, *, thread_id: str, user_text: str) -> AgentResult:
    turn_id = uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": thread_id}}
    user = Message(role="user", content=user_text)
    state = await graph.ainvoke(
        {
            "messages": [message_to_dict(user)],
            "trace": [_event(turn_id, 0, "turn_start", user_text=user_text)],
            "turn_id": turn_id,
            "steps": 0,
        },
        config,
    )
    trace = [event for event in state["trace"] if event["turn_id"] == turn_id]
    end = trace[-1]
    return AgentResult(
        answer=end["answer"],
        messages=[message_from_dict(m) for m in state["messages"]],
        stop_reason=end["stop_reason"],
        steps=end["steps"],
        trace=trace,
    )
