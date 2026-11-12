from datetime import UTC, datetime

import pytest

from nimbus.backend.db import connect_db, init_db
from nimbus.backend.seed import seed_db
from nimbus.backend.services import (
    DisputeAlreadyExistsError,
    IdempotencyConflictError,
    NotFoundError,
    ValidationError,
    get_transaction,
    open_dispute,
    request_refund,
)

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn():
    c = connect_db(":memory:")
    init_db(c)
    seed_db(c, seed=42)
    yield c
    c.close()


def test_get_transaction_returns_own_transaction(conn):
    tx = get_transaction(conn, "cust_pedro", "tx_withdrawal_confirming")
    assert tx["status"] == "confirming"


def test_get_transaction_hides_other_customers_transaction(conn):
    with pytest.raises(NotFoundError):
        get_transaction(conn, "cust_pedro", "tx_belongs_to_ricardo")


def count(conn, table):
    return conn.execute(f"select count (*) from {table}").fetchone()[0]


def test_open_dispute_creates_open_dispute(conn):
    dispute = open_dispute(
        conn, "cust_pedro", "tx_duplicate_charge_b", reason_code="duplicate", now=NOW
    )
    assert dispute["status"] == "open"
    assert dispute["reason_code"] == "duplicate"
    assert dispute["transaction_id"] == "tx_duplicate_charge_b"


def test_open_dispute_writes_audit_log(conn):
    before = count(conn, "audit_log")
    open_dispute(conn, "cust_pedro", "tx_duplicate_charge_b", reason_code="duplicate", now=NOW)
    assert count(conn, "audit_log") == before + 1


def test_open_dispute_rejects_invalid_reason(conn):
    with pytest.raises(ValidationError):
        open_dispute(conn, "cust_pedro", "tx_duplicate_charge_b", reason_code="banana", now=NOW)
    assert count(conn, "disputes") == 0


def test_open_dispute_on_other_customers_transaction(conn):
    with pytest.raises(NotFoundError):
        open_dispute(conn, "cust_pedro", "tx_belongs_to_ricardo", reason_code="duplicate", now=NOW)
    assert count(conn, "disputes") == 0


def test_open_dispute_twice_same_transaction(conn):
    open_dispute(conn, "cust_pedro", "tx_duplicate_charge_b", reason_code="duplicate", now=NOW)
    with pytest.raises(DisputeAlreadyExistsError):
        open_dispute(conn, "cust_pedro", "tx_duplicate_charge_b", reason_code="duplicate", now=NOW)
    assert count(conn, "disputes") == 1


def refund(conn, **overrides):
    args = {
        "customer_id": "cust_pedro",
        "transaction_id": "tx_duplicate_charge_b",
        "amount_minor": 34_900,
        "idempotency_key": "key-1",
        "now": NOW,
    }
    args.update(overrides)
    return request_refund(conn, **args)


def test_refund_below_threshold_approved(conn):
    r = refund(conn)
    assert r["status"] == "approved"
    assert r["requires_approval"] == 0


@pytest.mark.parametrize("amount", [0, -1, 34_901])
def test_refund_rejects_invalid_amount(conn, amount):
    with pytest.raises(ValidationError):
        refund(conn, amount_minor=amount)
    assert count(conn, "refund_requests") == 0


def test_refund_on_other_customers_transaction(conn):
    with pytest.raises(NotFoundError):
        refund(conn, transaction_id="tx_belongs_to_ricardo")


def test_refund_requires_completed_transaction(conn):
    with pytest.raises(ValidationError):
        refund(conn, transaction_id="tx_withdrawal_confirming", amount_minor=1_000)


def test_refund_writes_audit_log(conn):
    before = count(conn, "audit_log")
    refund(conn)
    assert count(conn, "audit_log") == before + 1


def test_refund_same_key_same_args_returns_same_result(conn):
    first = refund(conn)
    second = refund(conn)
    assert first["id"] == second["id"]
    assert count(conn, "refund_requests") == 1


def test_refund_same_key_different_args_conflicts(conn):
    refund(conn)
    with pytest.raises(IdempotencyConflictError):
        refund(conn, amount_minor=1_000)
    assert count(conn, "refund_requests") == 1


def test_refund_cannot_exceed_transaction_amount_total(conn):
    refund(conn, idempotency_key="key-1")
    with pytest.raises(ValidationError):
        refund(conn, idempotency_key="key-2", amount_minor=1_000)


def test_refund_above_threshold_needs_human_approval(conn):
    r = refund(conn, approval_threshold_minor=10_000)
    assert r["status"] == "pending_approval"
    assert r["requires_approval"] == 1
