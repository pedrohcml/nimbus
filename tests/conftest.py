from datetime import UTC, datetime

import pytest
from mcp import Client

from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import seed_db
from nimbus.mcp_server.server import build_server
from nimbus.mcp_server.session import Session

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


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
