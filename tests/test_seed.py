import pytest

from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import (
    TX_DUPLICATE_A,
    TX_DUPLICATE_B,
    TX_INJECTION_MEMO,
    TX_OTHER_CUSTOMER,
    TX_WITHDRAWAL_CONFIRMING,
    seed_db,
)


def make_db(seed: int):
    conn = connect_db(":memory:")
    init_db(conn)
    seed_db(conn, seed=seed)
    return conn


def dump(conn, table: str):
    rows = conn.execute(f"select * from {table} order by id").fetchall()
    return [tuple(row) for row in rows]


@pytest.mark.parametrize("table", ["customers", "wallets", "transactions"])
def test_same_seed_gives_same_data(table):
    assert dump(make_db(42), table) == dump(make_db(42), table)


def test_different_seed_gives_different_background_data():
    assert dump(make_db(1), "transactions") != dump(make_db(2), "transactions")


def test_seed_creates_enough_data():
    conn = make_db(42)
    customers = conn.execute("select count(*) from customers").fetchone()[0]
    transactions = conn.execute("select count(*) from transactions").fetchone()[0]
    assert customers >= 30
    assert transactions >= 200


def test_withdrawal_confirming_scenario():
    conn = make_db(42)
    tx = conn.execute(
        "select * from transactions where id = ?", (TX_WITHDRAWAL_CONFIRMING,)
    ).fetchone()
    assert tx["type"] == "withdrawal"
    assert tx["status"] == "confirming"
    assert tx["confirmations"] < tx["required_confirmations"]


def test_duplicate_charge_scenario():
    conn = make_db(42)
    a = conn.execute("select * from transactions where id = ?", (TX_DUPLICATE_A,)).fetchone()
    b = conn.execute("select * from transactions where id = ?", (TX_DUPLICATE_B,)).fetchone()
    assert a["customer_id"] == b["customer_id"]
    assert a["amount_minor"] == b["amount_minor"]
    assert a["asset"] == b["asset"]


def test_injection_memo_scenario():
    conn = make_db(42)
    row = conn.execute(
        "select counterparty_memo from transactions where id = ?", (TX_INJECTION_MEMO,)
    ).fetchone()
    assert "ignore" in row["counterparty_memo"].lower()


def test_other_customer_transaction_scenario():
    conn = make_db(42)
    mine = conn.execute(
        "select customer_id from transactions where id = ?", (TX_WITHDRAWAL_CONFIRMING,)
    ).fetchone()
    other = conn.execute(
        "select customer_id from transactions where id = ?", (TX_OTHER_CUSTOMER,)
    ).fetchone()
    assert mine["customer_id"] != other["customer_id"]
