from typing import Any, Protocol

from mcp import Client

from nimbus.agent.types import ToolSpec


class Tools(Protocol):
    async def specs(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]: ...


class McpTools:
    """Exposes an MCP client as the agent's toolbox"""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def specs(self) -> list[ToolSpec]:
        result = await self._client.list_tools()
        return [
            ToolSpec(name=t.name, description=t.description or "", input_schema=t.input_schema)
            for t in result.tools
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        result = await self._client.call_tool(name, arguments)
        text = "\n".join(
            block.text for block in result.content if getattr(block, "text", None) is not None
        )
        return text, bool(result.is_error)
