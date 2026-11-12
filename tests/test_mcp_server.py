from datetime import UTC, datetime
from typing import get_args

import pytest
from mcp import Client

from nimbus.backend import services
from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import seed_db
from nimbus.mcp_server.server import DisputeReason, build_server
from nimbus.mcp_server.session import Session

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def session():
    conn = connect_db(":memory:")
    init_db(conn)
    seed_db(conn, seed=42)
    return Session(
        conn=conn,
        customer_id="cust_pedro",
        conversation_id="conv-test",
        clock=lambda: NOW,
    )


@pytest.fixture
async def client(session):
    server = build_server(lambda: session)
    async with Client(server, raise_exceptions=True) as c:
        yield c


def count(conn, table):
    return conn.execute(f"select count (*) from {table}").fetchone()[0]


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


def test_dispute_reasons_match_service():
    assert set(get_args(DisputeReason)) == services.DISPUTE_REASONS


@pytest.mark.anyio
async def test_open_dispute_schema_lists_valid_reasons(client):
    result = await client.list_tools()
    tool = next(t for t in result.tools if t.name == "open_dispute")
    enum = tool.input_schema["properties"]["reason_code"]["enum"]
    assert set(enum) == services.DISPUTE_REASONS


@pytest.mark.anyio
async def test_open_dispute_creates_dispute(client, session):
    result = await client.call_tool(
        "open_dispute",
        {"transaction_id": "tx_duplicate_charge_b", "reason_code": "duplicate"},
    )
    assert not result.is_error
    assert result.structured_content["status"] == "open"
    assert "customer_id" not in result.structured_content
    assert count(session.conn, "disputes") == 1


@pytest.mark.anyio
async def test_open_dispute_rejects_unknown_reason(client, session):
    result = await client.call_tool(
        "open_dispute",
        {"transaction_id": "tx_duplicate_cahrge_b", "reason_code": "banana"},
    )
    assert result.is_error
    assert count(session.conn, "disputes") == 0


@pytest.mark.anyio
async def test_open_dispute_twice_reports_existing(client, session):
    args = {"transaction_id": "tx_duplicate_charge_b", "reason_code": "duplicate"}
    await client.call_tool("open_dispute", args)
    result = await client.call_tool("open_dispute", args)
    assert result.is_error
    assert "already exists" in result.content[0].text
    assert count(session.conn, "disputes") == 1


@pytest.mark.anyio
async def test_open_dispute_other_customers_transaction(client, session):
    result = await client.call_tool(
        "open_dispute",
        {"transaction_id": "tx_belongs_to_ricardo", "reason_code": "other"},
    )
    assert result.is_error
    assert "not found" in result.content[0].text
    assert count(session.conn, "disputes") == 0


@pytest.fixture
async def strict_client(session):
    server = build_server(lambda: session, refund_approval_threshold_minor=10_000)
    async with Client(server, raise_exceptions=True) as c:
        yield c


REFUND_ARGS = {"transaction_id": "tx_duplicate_charge_b", "amount_minor": 34_900}


@pytest.mark.anyio
async def test_idempotency_key_never_tool_argument(client):
    result = await client.list_tools()
    for tool in result.tools:
        assert "idempotency_key" not in tool.input_schema.get("properties", {})


@pytest.mark.anyio
async def test_refund_below_threshold_is_approved(client):
    result = await client.call_tool("request_refund", REFUND_ARGS)
    assert not result.is_error
    assert result.structured_content["status"] == "approved"
    assert result.structured_content["requires_approval"] is False


@pytest.mark.anyio
async def test_refund_above_threshold_waits_for_human(strict_client):
    result = await strict_client.call_tool("request_refund", REFUND_ARGS)
    assert not result.is_error
    assert result.structured_content["status"] == "pending_approval"
    assert result.structured_content["requires_approval"] is True


@pytest.mark.anyio
async def test_refund_rejects_non_positive_amount(client, session):
    result = await client.call_tool(
        "request_refund", {"transaction_id": "tx_duplicate_charge_b", "amount_minor": 0}
    )
    assert result.is_error
    assert count(session.conn, "refund_requests") == 0


@pytest.mark.anyio
async def test_refund_on_other_customers_transaction(client, session):
    result = await client.call_tool(
        "request_refund", {"transaction_id": "tx_belongs_to_ricardo", "amount_minor": 1_000}
    )
    assert result.is_error
    assert "not found" in result.content[0].text
    assert count(session.conn, "refund_requests") == 0
