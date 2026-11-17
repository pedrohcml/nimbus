import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import anyio
from dotenv import load_dotenv
from groq import APIError, AsyncGroq
from mcp import Client

from nimbus.agent.graph import build_agent_graph, run_graph_turn
from nimbus.agent.groq_llm import GroqLLM
from nimbus.agent.prompts import build_system_prompt
from nimbus.agent.settings import agent_model, groq_api_key
from nimbus.agent.tools import McpTools
from nimbus.agent.trace import write_trace
from nimbus.mcp_server.config import session_from_env
from nimbus.mcp_server.server import build_server

EXIT_WORDS = {"exit", "quit"}


async def main() -> None:
    load_dotenv()
    conversation_id = os.environ.setdefault(
        "NIMBUS_CONVERSATION_ID", f"conv_{uuid.uuid4().hex[:12]}"
    )
    llm = GroqLLM(AsyncGroq(api_key=groq_api_key()), agent_model())
    trace_path = Path("traces") / f"{conversation_id}.jsonl"

    async with Client(build_server(session_from_env)) as client:
        graph = await build_agent_graph(
            llm=llm,
            tools=McpTools(client),
            system_prompt=lambda: build_system_prompt(datetime.now(UTC)),
        )
        print(f"Nimbus ({agent_model()}). Conversation {conversation_id}. Type 'exit' to quit.")

        while True:
            user_text = (await anyio.to_thread.run_sync(input, "\nyou>")).strip()
            if not user_text:
                continue
            if user_text.lower() in EXIT_WORDS:
                break
            try:
                result = await run_graph_turn(graph, thread_id=conversation_id, user_text=user_text)
            except APIError as error:
                print(f"\n[error in the model provider: {type(error).__name__}] Try again.")
                continue
            write_trace(trace_path, result.trace)
            print(f"\nnimbus> {result.answer}")

    print(f"\nTrace saved in {trace_path}")


if __name__ == "__main__":
    anyio.run(main)
