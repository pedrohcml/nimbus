import pytest

from nimbus.backend.db import connect_db
from nimbus.backend.seed import create_demo_db
from nimbus.mcp_server.config import ConfigError, session_from_env


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    path = tmp_path / "demo.db"
    create_demo_db(path, seed=42)
    monkeypatch.setenv("NIMBUS_DB_PATH", str(path))
    return path


def test_create_demo_db_builds_seeded_file(tmp_path):
    path = tmp_path / "demo.db"
    create_demo_db(path, seed=42)
    conn = connect_db(str(path))
    assert conn.execute("select count (*) from customers").fetchone()[0] >= 30
    conn.close()


def test_create_demo_db_can_rebuild(tmp_path):
    path = tmp_path / "demo.db"
    create_demo_db(path, seed=42)
    create_demo_db(path, seed=42)


def test_session_requires_customer_id(demo_db, monkeypatch):
    monkeypatch.delenv("NIMBUS_CUSTOMER_ID", raising=False)
    with pytest.raises(ConfigError):
        session_from_env()


def test_session_rejects_unknown_customer(demo_db, monkeypatch):
    monkeypatch.setenv("NIMBUS_CUSTOMER_ID", "cust_ghost")
    with pytest.raises(ConfigError):
        session_from_env()


def test_session_requires_existing_db_file(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("NIMBUS_DB_PATH", str(missing))
    monkeypatch.setenv("NIMBUS_CUSTOMER_ID", "cust_pedro")
    with pytest.raises(ConfigError):
        session_from_env()
    assert not missing.exists()


def test_session_uses_values_from_env(demo_db, monkeypatch):
    monkeypatch.setenv("NIMBUS_CUSTOMER_ID", "cust_pedro")
    monkeypatch.setenv("NIMBUS_CONVERSATION_ID", "conv-42")
    session = session_from_env()
    assert session.customer_id == "cust_pedro"
    assert session.conversation_id == "conv-42"
    session.conn.close()
