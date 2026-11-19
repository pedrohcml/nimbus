from datetime import UTC, date, datetime
from typing import get_args

import pytest
from mcp import Client

from nimbus.backend import services
from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import (
    CUSTOMER_MAIN,
    TX_DUPLICATE_B,
    TX_OTHER_CUSTOMER,
    TX_WITHDRAWAL_CONFIRMING,
    seed_db,
)
from nimbus.mcp_server.server import DisputeReason, build_server
from nimbus.mcp_server.session import Session
from nimbus.rag.chunking import Chunk


class FakeRetriever:
    def __init__(self, chunks=(), error=None):
        self.chunks = list(chunks)
        self.error = error
        self.calls = []

    def search(self, query, k, on):
        self.calls.append((query, k, on))
        if self.error:
            raise self.error
        return self.chunks[:k]


POLICY_CHUNK = Chunk(
    id="refunds@v2#approval",
    policy_id="refunds",
    version=2,
    effective_from=date(2025, 11, 1),
    sections=("approval",),
    text="Refund policy - Approval\n\nUp to R$ 500.00 is approved automatically.",
)


NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


async def call_search(session, retriever, query="refund limit"):
    async with Client(build_server(lambda: session, retriever=retriever)) as client:
        return await client.call_tool("search_policies", {"query": query})


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
        customer_id=CUSTOMER_MAIN,
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
    result = await client.call_tool("get_transaction", {"transaction_id": TX_WITHDRAWAL_CONFIRMING})
    assert not result.is_error
    assert result.structured_content["status"] == "confirming"
    assert "customer_id" not in result.structured_content


@pytest.mark.anyio
async def test_get_transaction_other_customer_not_found(client):
    result = await client.call_tool("get_transaction", {"transaction_id": TX_OTHER_CUSTOMER})
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
        {"transaction_id": TX_DUPLICATE_B, "reason_code": "duplicate"},
    )
    assert not result.is_error
    assert result.structured_content["status"] == "open"
    assert "customer_id" not in result.structured_content
    assert count(session.conn, "disputes") == 1


@pytest.mark.anyio
async def test_open_dispute_rejects_unknown_reason(client, session):
    result = await client.call_tool(
        "open_dispute",
        {"transaction_id": TX_DUPLICATE_B, "reason_code": "banana"},
    )
    assert result.is_error
    assert count(session.conn, "disputes") == 0


@pytest.mark.anyio
async def test_open_dispute_twice_reports_existing(client, session):
    args = {"transaction_id": TX_DUPLICATE_B, "reason_code": "duplicate"}
    await client.call_tool("open_dispute", args)
    result = await client.call_tool("open_dispute", args)
    assert result.is_error
    assert "already exists" in result.content[0].text
    assert count(session.conn, "disputes") == 1


@pytest.mark.anyio
async def test_open_dispute_other_customers_transaction(client, session):
    result = await client.call_tool(
        "open_dispute",
        {"transaction_id": TX_OTHER_CUSTOMER, "reason_code": "other"},
    )
    assert result.is_error
    assert "not found" in result.content[0].text
    assert count(session.conn, "disputes") == 0


@pytest.fixture
async def strict_client(session):
    server = build_server(lambda: session, refund_approval_threshold_minor=10_000)
    async with Client(server, raise_exceptions=True) as c:
        yield c


REFUND_ARGS = {"transaction_id": TX_DUPLICATE_B, "amount_minor": 34_900}


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
        "request_refund", {"transaction_id": TX_DUPLICATE_B, "amount_minor": 0}
    )
    assert result.is_error
    assert count(session.conn, "refund_requests") == 0


@pytest.mark.anyio
async def test_refund_on_other_customers_transaction(client, session):
    result = await client.call_tool(
        "request_refund", {"transaction_id": TX_OTHER_CUSTOMER, "amount_minor": 1_000}
    )
    assert result.is_error
    assert "not found" in result.content[0].text
    assert count(session.conn, "refund_requests") == 0


@pytest.mark.anyio
async def test_conversation_id_never_tool_argument(client):
    result = await client.list_tools()
    for tool in result.tools:
        assert "conversation_id" not in tool.input_schema.get("properties", {})


@pytest.mark.anyio
async def test_escalate_opens_escalation_for_session_conversation(client, session):
    result = await client.call_tool(
        "escalate", {"reason": "Customer reports an unauthorized withdrawal."}
    )
    assert not result.is_error
    assert result.structured_content["status"] == "open"
    row = session.conn.execute("select conversation_id, customer_id from escalations").fetchone()
    assert row["conversation_id"] == "conv-test"
    assert row["customer_id"] == CUSTOMER_MAIN


@pytest.mark.anyio
async def test_escalate_twice_returns_same_escalation(client, session):
    args = {"reason": "Customer asks for a human agent."}
    first = await client.call_tool("escalate", args)
    second = await client.call_tool("escalate", args)
    assert first.structured_content["id"] == second.structured_content["id"]
    assert count(session.conn, "escalations") == 1


@pytest.mark.parametrize("reason", ["   ", "x" * 501])
@pytest.mark.anyio
async def test_escalate_rejects_invalid_reason(client, session, reason):
    result = await client.call_tool("escalate", {"reason": reason})
    assert result.is_error
    assert count(session.conn, "escalations") == 0


@pytest.mark.anyio
async def test_escalate_accepts_reason_at_max_length(client):
    result = await client.call_tool("escalate", {"reason": "x" * 500})
    assert not result.is_error


@pytest.mark.anyio
async def test_get_transaction_shows_delay_and_refundable_amount(client):
    result = await client.call_tool("get_transaction", {"transaction_id": TX_WITHDRAWAL_CONFIRMING})
    assert result.structured_content["delayed"] is True
    assert result.structured_content["refundable_minor"] == 0


@pytest.mark.anyio
async def test_refund_with_open_dispute_tells_model_why(client, session):
    await client.call_tool(
        "open_dispute", {"transaction_id": TX_DUPLICATE_B, "reason_code": "duplicate"}
    )
    result = await client.call_tool("request_refund", REFUND_ARGS)
    assert result.is_error
    assert "dispute" in result.content[0].text
    assert count(session.conn, "refund_requests") == 0


@pytest.mark.anyio
async def test_search_policies_returns_passages_for_session_date(session):
    retriever = FakeRetriever([POLICY_CHUNK])
    result = await call_search(session, retriever)
    assert not result.is_error
    [passage] = result.structured_content["passages"]
    assert passage["policy"] == "refunds"
    assert passage["version"] == 2
    assert "R$ 500.00" in passage["text"]
    assert retriever.calls == [("refund limit", 5, NOW.date())]


@pytest.mark.anyio
async def test_search_policies_without_retriever_is_error(session):
    result = await call_search(session, None)
    assert result.is_error
    assert "not available" in result.content[0].text


@pytest.mark.anyio
async def test_search_failure_hides_internal_details(session):
    retriever = FakeRetriever(error=RuntimeError("503 from pinecone-internal-host"))
    result = await call_search(session, retriever)
    assert "unavailable" in result.content[0].text
    assert "pinecone-internal-host" not in result.content[0].text
