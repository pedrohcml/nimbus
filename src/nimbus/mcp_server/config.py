import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from nimbus.backend.db import connect_db
from nimbus.mcp_server.session import Session

DEFAULT_DB_PATH = "data/nimbus.db"


class ConfigError(Exception):
    """The server can't start safely with the current configuration"""


def session_from_env() -> Session:
    db_path = Path(os.environ.get("NIMBUS_DB_PATH", DEFAULT_DB_PATH))
    if not db_path.is_file():
        raise ConfigError(f"database not found at {db_path}; run: uv run poe demo-db")

    customer_id = os.environ.get("NIMBUS_CUSTOMER_ID")
    if not customer_id:
        raise ConfigError("NIMBUS_CUSTOMER_ID is not set")

    conn = connect_db(str(db_path))
    found = conn.execute("select 1 from customers where id = ?", (customer_id,)).fetchone()
    if found is None:
        conn.close()
        raise ConfigError(f"customer {customer_id} not found in {db_path}")

    conversation_id = os.environ.get("NIMBUS_CONVERSATION_ID") or f"conv_{uuid.uuid4().hex[:12]}"
    return Session(
        conn=conn,
        customer_id=customer_id,
        conversation_id=conversation_id,
        clock=lambda: datetime.now(UTC),
    )
