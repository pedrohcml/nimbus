import os
import uuid
from pathlib import Path

import anyio
from dotenv import load_dotenv
from groq import APIError, AsyncGroq
from mcp import Client

from nimbus.agent.groq_llm import GroqLLM
from nimbus.agent.loop import run_turn
from nimbus.agent.prompts import SYSTEM_PROMPT
from nimbus.agent.tools import McpTools
from nimbus.agent.trace import write_trace
from nimbus.agent.types import Message
from nimbus.mcp_server.config import session_from_env
from nimbus.mcp_server.server import build_server

EXIT_WORDS = {"exit", "quit"}


async def main() -> None:
    load_dotenv()
    conversation_id = os.environ.setdefault(
        "NIMBUS_CONVERSATION_ID", f"conv_{uuid.uuid4().hex[:12]}"
    )
    model = os.environ.get("NIMBUS_AGENT_MODEL", "openai/gpt-oss-120b")
    llm = GroqLLM(AsyncGroq(), model)
    trace_path = Path("traces") / f"{conversation_id}.jsonl"

    async with Client(build_server(session_from_env)) as client:
        tools = McpTools(client)
        history: list[Message] = []
        print(f"Nimbus ({model}). Conversation {conversation_id}. Type 'exit' to quit.")

        while True:
            user_text = (await anyio.to_thread.run_sync(input, "\nyou>")).strip()
            if not user_text:
                continue
            if user_text.lower() in EXIT_WORDS:
                break
            try:
                result = await run_turn(
                    llm=llm,
                    tools=tools,
                    system_prompt=SYSTEM_PROMPT,
                    history=history,
                    user_text=user_text,
                )
            except APIError as error:
                print(f"\n[error in the model provider: {type(error).__anme__}] Try again.")
                continue
            write_trace(trace_path, result.trace)
            history = result.messages[1:]
            print(f"\nnimbus> {result.answer}")

    print(f"\nTrace saved in {trace_path}")


if __name__ == "__main__":
    anyio.run(main)
