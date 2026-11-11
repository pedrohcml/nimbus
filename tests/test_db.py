import sqlite3

import pytest

from nimbus.backend.db import connect_db, init_db

EXPECTED_TABLES = {
    "customers",
    "wallets",
    "transactions",
    "disputes",
    "refund_requests",
    "idempotency_keys",
    "escalations",
    "audit_log",
    "policy_documents",
}


@pytest.fixture
def connection():
    conn_db = connect_db(":memory:")
    init_db(conn_db)
    yield conn_db
    conn_db.close()


def test_init_db_create_tables(connection):
    rows = connection.execute(
        "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
    ).fetchall()
    assert {row["name"] for row in rows} == EXPECTED_TABLES


def test_foreign_keys(connection):
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "insert into wallets (id, customer_id, asset, balance_minor) "
            "values ('w1', 'randomcustomer', 'BTC', 0)"
        )


def test_check_constraint_rejects_invalid_kyc(connection):
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "insert into customers "
            "(id, full_name, email, country, kyc_status, created_at) "
            "values ('c1', 'Pedro', 'pedro@email.com', 'BR', 'pineapple', "
            "'2026-01-01T00:00:00+00:00')"
        )


def test_negative_wallet_balance(connection):
    connection.execute(
        "insert into customers "
        "(id, full_name, email, country, kyc_status, created_at) "
        "values ('c1', 'Pedro', 'pedro@email.com', 'BR', 'verified', "
        "'2026-01-01T00:00:00+00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "insert into wallets (id, customer_id, asset, balance_minor) "
            "values ('w1', 'c1', 'BTC', -1)"
        )
