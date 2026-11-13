"""Nimbus MCP server entry point"""

from nimbus.mcp_server.config import session_from_env
from nimbus.mcp_server.server import build_server

mcp = build_server(session_from_env)

if __name__ == "__main__":
    mcp.run()
