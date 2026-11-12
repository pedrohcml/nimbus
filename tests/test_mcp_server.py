from datetime import UTC, datetime

import pytest
from mcp import Client

from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import seed_db
from nimbus.mcp_server.server import build_server
from nimbus.mcp_server.session import Session

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_test_session(customer_id: str = "cust_pedro"):
    def factory() -> Session:
        conn = connect_db(":memory:")
        init_db(conn)
        seed_db(conn, seed=42)
        return Session(
            conn=conn,
            customer_id=customer_id,
            conversation_id="conv-test",
            clock=lambda: NOW,
        )

    return factory


@pytest.fixture
async def client():
    server = build_server(make_test_session())
    async with Client(server, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_customer_id_never_tool_argument(client):
    result = await client.list_tools()
    for tool in result.tools:
        assert "customer_id" not in tool.input_schema.get("properties", {})


@pytest.mark.anyio
async def test_server_lists_get_transaction(client):
    result = await client.list_tools()
    assert "get_transaction" in {tool.name for tool in result.tools}


@pytest.mark.anyio
async def test_get_transaction_returns_own_transaction(client):
    result = await client.call_tool(
        "get_transaction", {"transaction_id": "tx_withdrawal_confirming"}
    )
    assert not result.is_error
    assert result.structured_content["status"] == "confirming"
    assert "customer_id" not in result.structured_content


@pytest.mark.anyio
async def test_get_transaction_other_customer_not_found(client):
    result = await client.call_tool("get_transaction", {"transaction_id": "tx_belongs_to_ricardo"})
    assert result.is_error
    assert "not found" in result.content[0].text
