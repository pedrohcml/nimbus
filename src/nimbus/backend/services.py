import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta

DISPUTE_REASONS = {"unauthorized", "duplicate", "not_received", "wrong_amount", "other"}
DISPUTE_WINDOW = timedelta(days=14)
REFUND_APPROVAL_THRESHOLD_MINOR = 50_000
ESCALATION_REASON_MAX_LENGTH = 500


class ServiceError(Exception):
    """Base error. agent safe"""


class NotFoundError(ServiceError):
    """resource doesn't exist or does not belong to the caller"""


class ValidationError(ServiceError):
    """request with invalid value"""


class DisputeAlreadyExistsError(ServiceError):
    """dispute already exisntant for this transaction"""


class IdempotencyConflictError(ServiceError):
    """same idempotency key was reused w different arguments"""


def get_transaction(conn: sqlite3.Connection, customer_id: str, transaction_id: str) -> dict:
    row = conn.execute(
        "select * from transactions where id = ? and customer_id = ?",
        (transaction_id, customer_id),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"transaction {transaction_id} not found")
    return dict(row)


def _audit(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    customer_id: str,
    tool_name: str,
    args: dict,
    result_status: str,
) -> None:
    conn.execute(
        "insert into audit_log (ts, actor, customer_id, tool_name, args_json, result_status) "
        "values (?, ?, ?, ?, ?, ?)",
        (now.isoformat(), "agent", customer_id, tool_name, json.dumps(args), result_status),
    )


def open_dispute(
    conn: sqlite3.Connection,
    customer_id: str,
    transaction_id: str,
    reason_code: str,
    now: datetime,
) -> dict:
    if reason_code not in DISPUTE_REASONS:
        raise ValidationError(f"invalid reason_code: {reason_code}")

    with conn:
        get_transaction(conn, customer_id, transaction_id)

        existing = conn.execute(
            "select id from disputes where transaction_id = ?", (transaction_id,)
        ).fetchone()
        if existing is not None:
            raise DisputeAlreadyExistsError(f"dispute already exists for {transaction_id}")

        dispute = {
            "id": f"dsp_{uuid.uuid4().hex[:12]}",
            "customer_id": customer_id,
            "transaction_id": transaction_id,
            "reason_code": reason_code,
            "status": "open",
            "opened_at": now.isoformat(),
            "due_at": (now + DISPUTE_WINDOW).isoformat(),
        }
        conn.execute(
            "insert into disputes "
            "(id, customer_id, transaction_id, reason_code, status, opened_at, due_at) "
            "values (:id, :customer_id, :transaction_id, :reason_code, :status, "
            ":opened_at, :due_at)",
            dispute,
        )
        _audit(
            conn,
            now=now,
            customer_id=customer_id,
            tool_name="open_dispute",
            args={"transaction_id": transaction_id, "reason_code": reason_code},
            result_status="ok",
        )
    return dispute


def _request_hash(tool_name: str, payload: dict) -> str:
    canonical = json.dumps({"tool": tool_name, **payload}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def request_refund(
    conn: sqlite3.Connection,
    customer_id: str,
    transaction_id: str,
    amount_minor: int,
    idempotency_key: str,
    now: datetime,
    approval_threshold_minor: int = REFUND_APPROVAL_THRESHOLD_MINOR,
) -> dict:
    request_hash = _request_hash(
        "request_refund",
        {
            "customer_id": customer_id,
            "transaction_id": transaction_id,
            "amount_minor": amount_minor,
        },
    )

    with conn:
        stored = conn.execute(
            "select request_hash, response_json from idempotency_keys where key = ?",
            (idempotency_key,),
        ).fetchone()
        if stored is not None:
            if stored["request_hash"] != request_hash:
                raise IdempotencyConflictError(f"key {idempotency_key} reused with other args")
            return json.loads(stored["response_json"])

        tx = get_transaction(conn, customer_id, transaction_id)
        if tx["status"] != "completed":
            raise ValidationError(f"transaction is {tx['status']}, only completed can be refunded")
        if amount_minor <= 0 or amount_minor > tx["amount_minor"]:
            raise ValidationError("amount_minor must be between 1 and the transaction amount")

        already_requested = conn.execute(
            "select coalesce(sum(amount_minor), 0) from refund_requests "
            "where transaction_id = ? and status != 'rejected'",
            (transaction_id,),
        ).fetchone()[0]
        if already_requested + amount_minor > tx["amount_minor"]:
            raise ValidationError("total refunds for this transaction would exceed its amount")

        needs_approval = already_requested + amount_minor > approval_threshold_minor
        refund = {
            "id": f"rfd_{uuid.uuid4().hex[:12]}",
            "customer_id": customer_id,
            "transaction_id": transaction_id,
            "amount_minor": amount_minor,
            "asset": tx["asset"],
            "status": "pending_approval" if needs_approval else "approved",
            "requires_approval": int(needs_approval),
            "approved_by": None if needs_approval else "system:auto_policy",
            "decided_at": None if needs_approval else now.isoformat(),
            "created_at": now.isoformat(),
        }
        conn.execute(
            "insert into refund_requests "
            "(id, customer_id, transaction_id, amount_minor, asset, status, "
            "requires_approval, approved_by, decided_at, created_at) "
            "values (:id, :customer_id, :transaction_id, :amount_minor, :asset, :status, "
            ":requires_approval, :approved_by, :decided_at, :created_at)",
            refund,
        )
        conn.execute(
            "insert into idempotency_keys "
            "(key, tool_name, request_hash, response_json, created_at) values (?, ?, ?, ?, ?)",
            (idempotency_key, "request_refund", request_hash, json.dumps(refund), now.isoformat()),
        )
        _audit(
            conn,
            now=now,
            customer_id=customer_id,
            tool_name="request_refund",
            args={"transaction_id": transaction_id, "amount_minor": amount_minor},
            result_status=refund["status"],
        )
    return refund


def escalate(
    conn: sqlite3.Connection,
    customer_id: str,
    conversation_id: str,
    reason: str,
    now: datetime,
) -> dict:
    reason = reason.strip()
    if not reason or len(reason) > ESCALATION_REASON_MAX_LENGTH:
        raise ValidationError(f"reason must be 1-{ESCALATION_REASON_MAX_LENGTH} characters")

    with conn:
        customer = conn.execute("select id from customers where id = ?", (customer_id,)).fetchone()
        if customer is None:
            raise NotFoundError(f"customer {customer_id} not found")

        existing = conn.execute(
            "select * from escalations where conversation_id = ? and status = 'open'",
            (conversation_id,),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        escalation = {
            "id": f"esc_{uuid.uuid4().hex[:12]}",
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "reason": reason,
            "status": "open",
            "created_at": now.isoformat(),
        }
        conn.execute(
            "insert into escalations (id, conversation_id, customer_id, reason, status, "
            "created_at) values (:id, :conversation_id, :customer_id, :reason, :status, "
            ":created_at)",
            escalation,
        )
        _audit(
            conn,
            now=now,
            customer_id=customer_id,
            tool_name="escalate",
            args={"conversation_id": conversation_id},
            result_status="ok",
        )
    return escalation
